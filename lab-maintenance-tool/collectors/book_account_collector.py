"""
Book and Account Collector
Checks book availability/download state and automation account sign-in on Android devices.
"""
from typing import Dict, List, Any, Optional


REQUIRED_BOOK_COUNT = 10
AUTOMATION_ACCOUNT = "kindle-nft-automation"  # Expected automation testing account


def check_books_on_device(ssh_client, serial: str, adb_binary: str = "adb") -> Dict[str, Any]:
    """
    Check book availability and download status on an Android/FOS device.
    Returns count of books available and downloaded.
    """
    from collectors.ssh_collector import run_remote_command

    result = {
        "serial": serial,
        "books_available": 0,
        "books_downloaded": 0,
        "status": "unknown",
        "issues": []
    }

    try:
        # Check Kindle app book database via content provider or files
        # Method 1: Query Kindle content catalog database
        cmd = f'{adb_binary} -s {serial} shell "sqlite3 /data/data/com.amazon.kindle/databases/catalog.db \\"SELECT COUNT(*) FROM book_info WHERE is_owned=1;\\"" 2>/dev/null'
        out = run_remote_command(ssh_client, cmd)
        if out and out.strip().isdigit():
            result["books_available"] = int(out.strip())
        else:
            # Method 2: Count book files in download directory
            cmd2 = f'{adb_binary} -s {serial} shell "ls /sdcard/Android/data/com.amazon.kindle/files/content/ 2>/dev/null | wc -l"'
            out2 = run_remote_command(ssh_client, cmd2)
            if out2 and out2.strip().isdigit():
                result["books_available"] = int(out2.strip())

            # Method 3: For FOS devices
            cmd3 = f'{adb_binary} -s {serial} shell "ls /data/user/0/com.amazon.kindle/files/ 2>/dev/null | grep -c .azw"'
            out3 = run_remote_command(ssh_client, cmd3)
            if out3 and out3.strip().isdigit():
                count = int(out3.strip())
                if count > result["books_available"]:
                    result["books_available"] = count

        # Check downloaded state (files exist on device = downloaded)
        cmd_dl = f'{adb_binary} -s {serial} shell "find /sdcard/Android/data/com.amazon.kindle/files/ -name \'*.azw*\' 2>/dev/null | wc -l"'
        out_dl = run_remote_command(ssh_client, cmd_dl)
        if out_dl and out_dl.strip().isdigit():
            result["books_downloaded"] = int(out_dl.strip())
        else:
            # FOS path
            cmd_dl2 = f'{adb_binary} -s {serial} shell "find /data/user/0/com.amazon.kindle/files/ -name \'*.azw*\' 2>/dev/null | wc -l"'
            out_dl2 = run_remote_command(ssh_client, cmd_dl2)
            if out_dl2 and out_dl2.strip().isdigit():
                result["books_downloaded"] = int(out_dl2.strip())

        # Evaluate status
        if result["books_available"] >= REQUIRED_BOOK_COUNT:
            if result["books_downloaded"] >= REQUIRED_BOOK_COUNT:
                result["status"] = "Green"
            else:
                result["status"] = "Red"
                result["issues"].append(f"Only {result['books_downloaded']}/{REQUIRED_BOOK_COUNT} books downloaded")
        else:
            result["status"] = "Red"
            result["issues"].append(f"Only {result['books_available']}/{REQUIRED_BOOK_COUNT} books available")

    except Exception as e:
        result["status"] = "error"
        result["issues"].append(f"Check failed: {str(e)}")

    return result


def check_signed_in_account(ssh_client, serial: str, adb_binary: str = "adb") -> Dict[str, Any]:
    """
    Verify which account is signed in on the device.
    Must be the standard automation testing account.
    """
    from collectors.ssh_collector import run_remote_command

    result = {
        "serial": serial,
        "account": "unknown",
        "is_correct": False,
        "status": "unknown"
    }

    try:
        # Method 1: Check registered Amazon account
        cmd = f'{adb_binary} -s {serial} shell "dumpsys account | grep -i amazon | head -5"'
        out = run_remote_command(ssh_client, cmd)

        if out:
            # Extract account email/name from dumpsys output
            for line in out.splitlines():
                line = line.strip().lower()
                if '@' in line or 'name=' in line:
                    result["account"] = line.strip()
                    break

        # Method 2: Check Kindle app preferences for signed-in user
        if result["account"] == "unknown":
            cmd2 = f'{adb_binary} -s {serial} shell "cat /data/data/com.amazon.kindle/shared_prefs/KindlePreferences.xml 2>/dev/null | grep -i account | head -3"'
            out2 = run_remote_command(ssh_client, cmd2)
            if out2:
                result["account"] = out2.strip()[:80]

        # Method 3: For FOS devices - check system account
        if result["account"] == "unknown":
            cmd3 = f'{adb_binary} -s {serial} shell "settings get secure account_name 2>/dev/null"'
            out3 = run_remote_command(ssh_client, cmd3)
            if out3 and out3.strip() and out3.strip() != "null":
                result["account"] = out3.strip()

        # Validate account
        if AUTOMATION_ACCOUNT.lower() in result["account"].lower():
            result["is_correct"] = True
            result["status"] = "Green"
        elif result["account"] == "unknown":
            result["status"] = "Yellow"
            result["account"] = "Could not determine"
        else:
            result["status"] = "Red"

    except Exception as e:
        result["status"] = "error"
        result["account"] = f"Error: {str(e)}"

    return result


def check_all_devices_books_and_accounts(
    ssh_client, serials: List[str], adb_binary: str = "adb"
) -> Dict[str, Dict[str, Any]]:
    """
    Run book and account checks across all connected devices.
    Returns dict keyed by serial number.
    """
    results = {}
    for serial in serials:
        results[serial] = {
            "books": check_books_on_device(ssh_client, serial, adb_binary),
            "account": check_signed_in_account(ssh_client, serial, adb_binary),
        }
    return results
