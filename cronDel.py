from pyVim.connect import SmartConnect, Disconnect
from pyVmomi import vim
import ssl
import atexit
from datetime import datetime, timedelta
import requests
from vmware.vapi.vsphere.client import create_vsphere_client
import argparse

# ===== Configuration =====
VCENTER_HOST = "192.168.2.58"
VCENTER_PORT = 443

TAG_CATEGORY_TIMESTAMP = "Timestamp"
TAG_CATEGORY_CLONE = "Clone"
CLONE_TAG_NAME = "LinkedClone"
DELETE_AFTER_MINUTES = 5
# ==========================

requests.packages.urllib3.disable_warnings()
context = ssl._create_unverified_context()


def wait_for_task(task):
    while task.info.state not in [vim.TaskInfo.State.success, vim.TaskInfo.State.error]:
        pass
    if task.info.state == vim.TaskInfo.State.error:
        raise task.info.error
    return task.info.result


if __name__ == "__main__":

    parser = argparse.ArgumentParser()
    parser.add_argument("--username", help="vCenter username")
    parser.add_argument("--password", help="vCenter password")
    args = parser.parse_args()

    VCENTER_USER = args.username or os.environ.get("VCENTER_USER")
    VCENTER_PASSWORD = args.password or os.environ.get("VCENTER_PASSWORD")

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

        # Connect vAPI
        session = requests.session()
        session.verify = False
        client = create_vsphere_client(
            server=VCENTER_HOST,
            username=VCENTER_USER,
            password=VCENTER_PASSWORD,
            session=session
        )
        print("[INFO] Connected to vCenter (vAPI)")

        assoc_svc = client.tagging.TagAssociation
        tag_svc = client.tagging.Tag
        category_svc = client.tagging.Category

        clone_tag_id = None
        for t_id in tag_svc.list():
            t_info = tag_svc.get(t_id)
            if t_info.name == CLONE_TAG_NAME:
                clone_tag_id = t_id
                break
        if not clone_tag_id:
            print("[INFO] No LinkedClone tag found, exiting.")
            exit(0)

        vm_ids = assoc_svc.list_attached_objects(clone_tag_id)
        print(f"[INFO] Found {len(vm_ids)} LinkedClone VMs attached to tag.")

        for vm_ref in vm_ids:
            content = si.RetrieveContent()
            vm = None
            container = content.viewManager.CreateContainerView(content.rootFolder, [vim.VirtualMachine], True)
            for c in container.view:
                if c._moId == vm_ref.id:
                    vm = c
                    break
            container.Destroy()
            if not vm:
                print(f"[WARN] VM {vm_ref.id} not found, skipping.")
                continue

            ts_tag_id = None
            ts_tag_name = None
            for t_id in tag_svc.list():
                t_info = tag_svc.get(t_id)
                if t_info.name.startswith("TS_"):
                    attached_objs = assoc_svc.list_attached_objects(t_id)
                    if any(obj.id == vm._moId for obj in attached_objs):
                        ts_tag_id = t_id
                        ts_tag_name = t_info.name
                        break

            if not ts_tag_id or not ts_tag_name:
                print(f"[WARN] VM {vm.name} has no Timestamp tag, skipping.")
                continue

            ts_str = ts_tag_name[3:]  
            ts_dt = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
            if datetime.now() - ts_dt < timedelta(minutes=DELETE_AFTER_MINUTES):
                print(f"[INFO] VM {vm.name} is younger than {DELETE_AFTER_MINUTES} minutes, skipping.")
                continue

            if vm.runtime.powerState == vim.VirtualMachinePowerState.poweredOn:
                print(f"[INFO] Powering off VM {vm.name}...")
                wait_for_task(vm.PowerOffVM_Task())

            print(f"[INFO] Destroying VM {vm.name}...")
            vm_ = vm.name
            wait_for_task(vm.Destroy_Task())
            print(f"[SUCCESS] VM {vm_} deleted.")

    except Exception as e:
        print(f"[ERROR] {e}")

