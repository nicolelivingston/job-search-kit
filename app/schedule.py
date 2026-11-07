#!/usr/bin/env python3
"""Install or remove the agent's daily schedule.

    python3 app/schedule.py install     # register the runs
    python3 app/schedule.py remove      # unregister them
    python3 app/schedule.py show        # print what would be registered

Windows: two Task Scheduler tasks (registered from XML so "run as soon as
possible after a missed start" is on; a computer asleep at 8am runs the job
when it wakes). macOS: two launchd agents in ~/Library/LaunchAgents (launchd
runs a missed calendar job on wake by itself).

Times come from settings/app.json:
  "schedule": {"full": "08:00", "quick": ["11:00", "14:00", "17:00", "20:00"], "update": "09:30"}
A third task runs the updater once a day (it installs only releases signed
with the maintainer's key), unless "auto_update" is false in app.json.
The full run fetches, scores, rescores the tracker, and closes stale
postings; quick runs only fetch and write new postings.
Output goes to <data folder>/agent.log.
"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from xml.sax.saxutils import escape

APP = Path(__file__).resolve().parent
sys.path.insert(0, str(APP))
from kit_settings import app_settings, data_dir  # noqa: E402

TASK_PREFIX = "Job Search Kit"
LABEL_PREFIX = "com.jobsearchkit.agent"
DEFAULT = {"full": "08:00", "quick": ["11:00", "14:00", "17:00", "20:00"]}


def schedule():
    s = dict(DEFAULT)
    s.update(app_settings().get("schedule") or {})
    return s


def runs():
    s = schedule()
    out = [("full", [s["full"]], [])]
    if s.get("quick"):
        out.append(("quick", list(s["quick"]), ["--quick"]))
    return out


def _hm(t):
    h, m = t.split(":")
    return int(h), int(m)


def windows_command(python, agent, log, extra):
    # cmd /c so output can be appended to the log; PYTHONUTF8 keeps file
    # reads and writes in UTF-8 on Windows.
    args = " ".join(extra)
    inner = f'set PYTHONUTF8=1&& "{python}" "{agent}" {args} >> "{log}" 2>&1'.replace("  ", " ")
    return "cmd.exe", f'/c "{inner}"'


def windows_task_xml(name, times, python, agent, log, extra, workdir):
    trig = "\n".join(
        f"""    <CalendarTrigger>
      <StartBoundary>2026-01-01T{h:02d}:{m:02d}:00</StartBoundary>
      <Enabled>true</Enabled>
      <ScheduleByDay><DaysInterval>1</DaysInterval></ScheduleByDay>
    </CalendarTrigger>""" for h, m in map(_hm, times))
    exe, args = windows_command(python, agent, log, extra)
    return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo><Description>{escape(name)}: job search agent</Description></RegistrationInfo>
  <Triggers>
{trig}
  </Triggers>
  <Principals><Principal id="Author"><LogonType>InteractiveToken</LogonType><RunLevel>LeastPrivilege</RunLevel></Principal></Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>true</RunOnlyIfNetworkAvailable>
    <ExecutionTimeLimit>PT1H</ExecutionTimeLimit>
    <Enabled>true</Enabled>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{escape(exe)}</Command>
      <Arguments>{escape(args)}</Arguments>
      <WorkingDirectory>{escape(str(workdir))}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"""


def mac_plist(label, times, python, agent, log, extra, workdir):
    cal = "\n".join(f"    <dict><key>Hour</key><integer>{h}</integer><key>Minute</key><integer>{m}</integer></dict>"
                    for h, m in map(_hm, times))
    prog = "\n".join(f"    <string>{escape(a)}</string>" for a in [python, str(agent), *extra])
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>{label}</string>
  <key>ProgramArguments</key>
  <array>
{prog}
  </array>
  <key>WorkingDirectory</key><string>{escape(str(workdir))}</string>
  <key>StartCalendarInterval</key>
  <array>
{cal}
  </array>
  <key>StandardOutPath</key><string>{escape(str(log))}</string>
  <key>StandardErrorPath</key><string>{escape(str(log))}</string>
</dict>
</plist>
"""


def plan(platform=None, python=None):
    platform = platform or sys.platform
    python = python or sys.executable
    agent = APP / "agent" / "job_search_agent.py"
    updater = APP / "updater.py"
    log = data_dir() / "agent.log"
    for path in (python, agent, log):
        if '"' in str(path):
            sys.exit(f"The path {path} contains a double quote, which the scheduler can't pass safely. Rename the folder.")
    items = []
    jobs = [(kind, times, agent, extra) for kind, times, extra in runs()]
    if app_settings().get("auto_update", True) is not False:   # the user can turn automatic updates off
        jobs.append(("update check", [schedule().get("update", "09:30")], updater, []))   # signed releases only; see updater.py
    for kind, times, script, extra in jobs:
        if platform.startswith("win"):
            name = f"{TASK_PREFIX} ({kind})"
            items.append((name, windows_task_xml(name, times, python, script, log, extra, agent.parent)))
        else:
            label = f"{LABEL_PREFIX}.{kind.replace(' ', '-')}"
            items.append((label, mac_plist(label, times, python, script, log, extra, agent.parent)))
    return items


def install():
    if sys.platform.startswith("win"):
        for name, xml in plan():
            with tempfile.NamedTemporaryFile("w", suffix=".xml", delete=False, encoding="utf-16") as fh:
                fh.write(xml)
            subprocess.run(["schtasks", "/Create", "/F", "/TN", name, "/XML", fh.name], check=True)
            os.unlink(fh.name)
    elif sys.platform == "darwin":
        la = Path.home() / "Library" / "LaunchAgents"
        la.mkdir(parents=True, exist_ok=True)
        for label, xml in plan():
            f = la / f"{label}.plist"
            subprocess.run(["launchctl", "unload", str(f)], capture_output=True)
            f.write_text(xml)
            subprocess.run(["launchctl", "load", str(f)], check=True)
    else:
        sys.exit("Scheduling is supported on Windows and macOS.")
    print("Schedule installed:", ", ".join(n for n, _ in plan()))


def remove():
    if sys.platform.startswith("win"):
        for name, _ in plan():
            subprocess.run(["schtasks", "/Delete", "/F", "/TN", name], capture_output=True)
    elif sys.platform == "darwin":
        for label, _ in plan():
            f = Path.home() / "Library" / "LaunchAgents" / f"{label}.plist"
            subprocess.run(["launchctl", "unload", str(f)], capture_output=True)
            if f.exists():
                f.unlink()
    print("Schedule removed.")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "show"
    if cmd == "install":
        install()
    elif cmd == "remove":
        remove()
    else:
        for name, text in plan():
            print(f"===== {name}\n{text}")
