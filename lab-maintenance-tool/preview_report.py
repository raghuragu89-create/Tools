"""Saves a preview of the HTML report to disk without sending email."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from lab_report import load_config, collect_machine_data, collect_device_counts, collect_android_perf_status, build_auto_callouts
from reporters.html_report import build_html
from datetime import date

cfg = load_config("config.yaml")
machines       = collect_machine_data(cfg)
device_counts  = collect_device_counts(cfg)
android_status = collect_android_perf_status(cfg)
callouts       = build_auto_callouts(machines)

html = build_html(machines, device_counts, android_status, callouts, date.today())
with open("report_preview.html", "w") as f:
    f.write(html)
print("Saved to report_preview.html")
