from pyVim.connect import SmartConnect, Disconnect
from pyVmomi import vim
import ssl
import atexit
from datetime import datetime
import requests
from vmware.vapi.vsphere.client import create_vsphere_client
import argparse

# ===== Configuration =====
VCENTER_HOST = "192.168.2.58"
VCENTER_PORT = 443

SOURCE_NAME = "temp1"          # Template or VM name
DATASTORE_NAME = "datastore1"  # Datastore name
CLUSTER_NAME = "home"           # Cluster name
FOLDER_NAME = "vm"             # Folder name for the new VM
HOST_NAME = "192.168.2.60"     # Host to place the VM if converting from Template
TAG_CATEGORY_TIMESTAMP = "Timestamp"
TAG_CATEGORY_CLONE = "Clone"
# ==========================

# Disable SSL warnings
requests.packages.urllib3.disable_warnings()
context = ssl._create_unverified_context()


def wait_for_task(task):
    while task.info.state not in [vim.TaskInfo.State.success, vim.TaskInfo.State.error]:
        pass
    if task.info.state == vim.TaskInfo.State.error:
        raise task.info.error
    return task.info.result


def get_obj(content, vimtype, name):
    obj = None
    container = content.viewManager.CreateContainerView(
        content.rootFolder, vimtype, True
    )
    for c in container.view:
        if c.name == name:
            obj = c
            break
    container.Destroy()
    return obj


def ensure_vm_with_snapshot(content, source_name, host_name):
    obj = get_obj(content, [vim.VirtualMachine], source_name)
    if not obj:
        raise Exception(f"Source {source_name} not found.")

    converted_to_vm = False

    if obj.config.template:
        print(f"[INFO] Source '{source_name}' is a Template. Converting to VM...")
        host = get_obj(content, [vim.HostSystem], host_name)
        if not host:
            raise Exception(f"Host '{host_name}' not found.")
        resource_pool = host.parent.resourcePool
        wait_for_task(obj.MarkAsVirtualMachine(resource_pool, host))
        obj = get_obj(content, [vim.VirtualMachine], source_name)
        converted_to_vm = True
        print(f"[INFO] Converted template '{source_name}' to VM.")

    if not obj.snapshot:
        print(f"[INFO] No snapshot found for '{source_name}', creating one...")
        snap_task = obj.CreateSnapshot_Task(
            name="BaseSnapshot",
            description="Snapshot for linked clone",
            memory=False,
            quiesce=False
        )
        wait_for_task(snap_task)
        obj = get_obj(content, [vim.VirtualMachine], source_name)
        print(f"[INFO] Snapshot created for '{source_name}'.")

    return obj, converted_to_vm


def create_linked_clone(content, source_vm, new_vm_name, datastore_name, cluster_name, folder_name):
    snapshot = source_vm.snapshot.rootSnapshotList[0].snapshot

    datastore = get_obj(content, [vim.Datastore], datastore_name)
    if not datastore:
        raise Exception(f"Datastore {datastore_name} not found.")

    cluster = get_obj(content, [vim.ClusterComputeResource], cluster_name)
    if not cluster:
        raise Exception(f"Cluster {cluster_name} not found.")
    resource_pool = cluster.resourcePool

    folder = get_obj(content, [vim.Folder], folder_name)
    if not folder:
        print(f"[WARN] Folder '{folder_name}' not found, using root folder.")
        folder = content.rootFolder

    relocate_spec = vim.vm.RelocateSpec()
    relocate_spec.datastore = datastore
    relocate_spec.pool = resource_pool
    relocate_spec.diskMoveType = 'createNewChildDiskBacking'  # Linked Clone

    clone_spec = vim.vm.CloneSpec(
        location=relocate_spec,
        powerOn=True,
        template=False,
        snapshot=snapshot
    )

    print(f"[INFO] Creating linked clone '{new_vm_name}' from '{source_vm.name}'...")
    task = source_vm.CloneVM_Task(folder=folder, name=new_vm_name, spec=clone_spec)
    wait_for_task(task)
    print(f"[SUCCESS] Linked clone '{new_vm_name}' created successfully.")


def assign_tag(client, vm_obj, tag_name, category_name, description):
    """
    Assign a tag to a VM. Creates category and tag if they do not exist.
    """
    category_svc = client.tagging.Category
    tag_svc = client.tagging.Tag
    assoc_svc = client.tagging.TagAssociation

    # Check/create category
    categories = category_svc.list()
    cat_id = None
    for c in categories:
        info = category_svc.get(c)
        if info.name == category_name:
            cat_id = c
            break
    if not cat_id:
        spec = category_svc.CreateSpec(
            name=category_name,
            description=f"{category_name} category",
            cardinality="SINGLE",
            associable_types={"VirtualMachine"}  # ✅ set במקום list
        )
        cat_id = category_svc.create(spec)

    # Check/create tag
    tags = tag_svc.list()
    tag_id = None
    for t in tags:
        info = tag_svc.get(t)
        if info.name == tag_name:
            tag_id = t
            break
    if not tag_id:
        tag_spec = tag_svc.CreateSpec(
            name=tag_name,
            description=description,
            category_id=cat_id
        )
        tag_id = tag_svc.create(tag_spec)

    # Attach tag
    vm_id = {'type': 'VirtualMachine', 'id': vm_obj._moId}
    assoc_svc.attach(tag_id, vm_id)
    print(f"[INFO] Assigned tag '{tag_name}' to VM '{vm_obj.name}'")


def assign_tags_for_clone(client, vm_obj):
    """
    Assign both Timestamp and Clone tags to VM.
    """
    timestamp_tag = f"TS_{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    assign_tag(client, vm_obj, timestamp_tag, TAG_CATEGORY_TIMESTAMP, "Timestamp tag")
    assign_tag(client, vm_obj, "LinkedClone", TAG_CATEGORY_CLONE, "Mark VM as linked clone")


def revert_to_template_if_needed(vm_obj, was_template):
    if was_template:
        print(f"[INFO] Reverting '{vm_obj.name}' back to Template...")
        wait_for_task(vm_obj.MarkAsTemplate())
        print(f"[SUCCESS] '{vm_obj.name}' is now a Template again.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--username", help="vCenter username")
    parser.add_argument("--password", help="vCenter password")
    parser.add_argument("--env",      help="name for env")
    args = parser.parse_args()

    VCENTER_USER = args.username
    VCENTER_PASSWORD = args.password 
    NEW_VM_NAME = args.env


    if not VCENTER_USER or not VCENTER_PASSWORD:
        raise ValueError("Username and password must be provided either as arguments or environment variables.")
    try:
        # Connect pyVmomi
        si = SmartConnect(
            host=VCENTER_HOST,
            user=VCENTER_USER,
            pwd=VCENTER_PASSWORD,
            port=VCENTER_PORT,
            sslContext=context
        )
        atexit.register(Disconnect, si)
        print("[INFO] Connected to vCenter (pyVmomi)")

        content = si.RetrieveContent()

        # Connect vSphere Automation (vAPI) client
        session = requests.session()
        session.verify = False
        client = create_vsphere_client(
            server=VCENTER_HOST,
            username=VCENTER_USER,
            password=VCENTER_PASSWORD,
            session=session
        )
        print("[INFO] Connected to vCenter (vAPI)")

        # Ensure VM with snapshot
        vm_source, was_template = ensure_vm_with_snapshot(content, SOURCE_NAME, HOST_NAME)

        # Create linked clone
        create_linked_clone(content, vm_source, NEW_VM_NAME, DATASTORE_NAME, CLUSTER_NAME, FOLDER_NAME)

        # Get new VM object
        new_vm = get_obj(content, [vim.VirtualMachine], NEW_VM_NAME)

        # Assign both Timestamp and Clone tags
        assign_tags_for_clone(client, new_vm)

        # Revert source VM to template if needed
        revert_to_template_if_needed(vm_source, was_template)

    except Exception as e:
        print(f"[ERROR] {e}")

