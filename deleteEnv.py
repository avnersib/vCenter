from pyVim.connect import SmartConnect, Disconnect
from pyVmomi import vim
import ssl
import atexit
import requests
from vmware.vapi.vsphere.client import create_vsphere_client
import argparse
import os

# ===== Configuration =====
VCENTER_HOST = "192.168.2.58"
VCENTER_PORT = 443
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
    parser.add_argument("--vmname", help="Exact VM name to delete")
    args = parser.parse_args()

    VCENTER_USER = args.username or os.environ.get("VCENTER_USER")
    VCENTER_PASSWORD = args.password or os.environ.get("VCENTER_PASSWORD")
    VM_TO_DELETE = args.vmname

    if not VCENTER_USER or not VCENTER_PASSWORD:
        raise ValueError("Username and password must be provided either as arguments or environment variables.")
    if not VM_TO_DELETE:
        raise ValueError("VM name must be provided with --vmname.")

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

        content = si.RetrieveContent()
        container = content.viewManager.CreateContainerView(content.rootFolder, [vim.VirtualMachine], True)

        vm_to_delete = None
        for vm in container.view:
            if vm.name == VM_TO_DELETE:
                vm_to_delete = vm
                break
        container.Destroy()

        if not vm_to_delete:
            print(f"[ERROR] VM '{VM_TO_DELETE}' not found.")
            exit(1)

        if vm_to_delete.runtime.powerState == vim.VirtualMachinePowerState.poweredOn:
            print(f"[INFO] Powering off VM {vm_to_delete.name}...")
            wait_for_task(vm_to_delete.PowerOffVM_Task())

        print(f"[INFO] Destroying VM {vm_to_delete.name}...")
        vmName = {vm_to_delete.name}
        wait_for_task(vm_to_delete.Destroy_Task())
        print(f"[SUCCESS] VM {vmName} deleted.")

    except Exception as e:
        print(f"[ERROR] {e}")
