from pyVim.connect import SmartConnect, Disconnect
from pyVmomi import vim
import ssl
import atexit
import requests
from vmware.vapi.vsphere.client import create_vsphere_client
import argparse
from datetime import datetime

VCENTER_HOST = "192.168.2.58"
VCENTER_PORT = 443
TAG_CATEGORY_TIMESTAMP = "Timestamp"

requests.packages.urllib3.disable_warnings()
context = ssl._create_unverified_context()

def get_vm_by_name(content, vm_name):
    container = content.viewManager.CreateContainerView(content.rootFolder, [vim.VirtualMachine], True)
    vm_obj = None
    for vm in container.view:
        if vm.name == vm_name:
            vm_obj = vm
            break
    container.Destroy()
    return vm_obj

def assign_timestamp_tag(client, vm_obj):
    category_svc = client.tagging.Category
    tag_svc = client.tagging.Tag
    assoc_svc = client.tagging.TagAssociation

    cat_id = None
    for c in category_svc.list():
        info = category_svc.get(c)
        if info.name == TAG_CATEGORY_TIMESTAMP:
            cat_id = c
            break
    if not cat_id:
        spec = category_svc.CreateSpec(
            name=TAG_CATEGORY_TIMESTAMP,
            description="Timestamp category",
            cardinality="SINGLE",
            associable_types={"VirtualMachine"}
        )
        cat_id = category_svc.create(spec)

    for t_id in tag_svc.list():
        t_info = tag_svc.get(t_id)
        if t_info.category_id == cat_id:
            attached_objs = assoc_svc.list_attached_objects(t_id)
            for obj in attached_objs:
                if obj.id == vm_obj._moId:
                    assoc_svc.detach(t_id, {'type': 'VirtualMachine', 'id': vm_obj._moId})

    timestamp_tag_name = f"TS_{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    tag_id = None
    for t in tag_svc.list():
        info = tag_svc.get(t)
        if info.name == timestamp_tag_name:
            tag_id = t
            break
    if not tag_id:
        tag_spec = tag_svc.CreateSpec(
            name=timestamp_tag_name,
            description="Updated Timestamp",
            category_id=cat_id
        )
        tag_id = tag_svc.create(tag_spec)

    assoc_svc.attach(tag_id, {'type': 'VirtualMachine', 'id': vm_obj._moId})
    print(f"Updated Timestamp tag for VM '{vm_obj.name}' to '{timestamp_tag_name}'")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--username", help="vCenter username")
    parser.add_argument("--password", help="vCenter password")
    parser.add_argument("--vmname", help="VM name to update timestamp")
    args = parser.parse_args()

    VCENTER_USER = args.username
    VCENTER_PASSWORD = args.password
    VM_NAME = args.vmname

    if not VCENTER_USER or not VCENTER_PASSWORD or not VM_NAME:
        raise ValueError("Username, password, and VM name must be provided.")

    si = SmartConnect(host=VCENTER_HOST, user=VCENTER_USER, pwd=VCENTER_PASSWORD, port=VCENTER_PORT, sslContext=context)
    atexit.register(Disconnect, si)
    content = si.RetrieveContent()

    session = requests.session()
    session.verify = False
    client = create_vsphere_client(server=VCENTER_HOST, username=VCENTER_USER, password=VCENTER_PASSWORD, session=session)

    vm_obj = get_vm_by_name(content, VM_NAME)
    if not vm_obj:
        print(f"VM '{VM_NAME}' not found.")
        exit(1)

    assign_timestamp_tag(client, vm_obj)

