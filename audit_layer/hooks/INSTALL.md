# Starting the sweep by hook and by schedule

The sweep stores every AI session a harness keeps that the audit store does not yet hold whole. Appendix A2.4 runs it while a session runs, when it ends, and again on a schedule. This folder holds the two pieces that start it at those times. The repository installs nothing. You add each piece by hand, and you can take each one out again.

## What each piece does

- `claude_code_hook.py` is the script Claude Code runs at the end of each turn (`Stop`), when a subagent finishes (`SubagentStop`), and when a session ends (`SessionEnd`). It reads the session file's path from the hook's input and starts `python3 -m audit_layer sweep --harness claude_code --file <path>` as a separate process, so a turn never waits on capture. It always exits 0 and prints nothing. The sweep's output and any line about input the script could not use go to `hook.log` in the audit home, and they name sessions by id, never by path.
- `schedule/audit_layer.sweep.plist` is a launchd agent template for macOS that runs `python3 -m audit_layer sweep` every 1,800 seconds (30 minutes). The schedule catches any session the hook missed, and ForgeCode sessions, since ForgeCode has no hook here.
- The crontab line below does what the plist does, for a machine that uses cron instead.

## First, set up the audit home

Do this before installing anything.

1. Run `python3 -m audit_layer init` from the repository folder. It makes the audit home (`~/.audit_layer`, or the folder `AUDIT_HOME` names) and writes `settings.yaml` there.
2. List under `excluded_folders` in `settings.yaml` every folder that holds student records, and any other folder whose AI sessions must never be kept. Either edit the file, or run `python3 -m audit_layer excluded add PATH`, giving each folder as a full path starting with / or ~. The command adds and never removes, and `python3 -m audit_layer excluded list` prints the list. A session run in a listed folder is never recorded. The sweep does not run until this file exists.
3. Run `python3 -m audit_layer sweep` once by hand and read its summary.

## The Claude Code hook

Add the hook commands to the `hooks` block of `~/.claude/settings.json` by hand. If the file already has a `hooks` block, add these three events to it, or add the one command to an event already listed there. Never replace an existing `hooks` block, since that would drop the hooks already in it. Replace `REPO_PATH` with the full path of the repository folder.

```json
{
  "hooks": {
    "Stop": [
      {
        "hooks": [
          {"type": "command", "command": "python3 REPO_PATH/audit_layer/hooks/claude_code_hook.py"}
        ]
      }
    ],
    "SubagentStop": [
      {
        "hooks": [
          {"type": "command", "command": "python3 REPO_PATH/audit_layer/hooks/claude_code_hook.py"}
        ]
      }
    ],
    "SessionEnd": [
      {
        "hooks": [
          {"type": "command", "command": "python3 REPO_PATH/audit_layer/hooks/claude_code_hook.py"}
        ]
      }
    ]
  }
}
```

The `python3` here must be one that has PyYAML, since the sweep it starts uses the same Python. If your audit home is not `~/.audit_layer`, set `AUDIT_HOME` in the environment Claude Code runs in.

To remove the hook, delete those three commands from `~/.claude/settings.json` and leave the rest of the file as it was.

## The schedule on macOS

1. Copy `schedule/audit_layer.sweep.plist` to `~/Library/LaunchAgents/audit_layer.sweep.plist`.
2. In the copy, replace `PYTHON_PATH` with the full path of your `python3` (as `which python3` prints it) and `REPO_PATH` with the full path of the repository folder. If your audit home is not `~/.audit_layer`, add an `EnvironmentVariables` entry that sets `AUDIT_HOME`.
3. Run `launchctl load ~/Library/LaunchAgents/audit_layer.sweep.plist`.

To remove it, run `launchctl unload ~/Library/LaunchAgents/audit_layer.sweep.plist` and delete the copy.

## The schedule with cron

Run `crontab -e` and add this line, with the two values replaced as for the plist.

```
*/30 * * * * cd REPO_PATH && PYTHON_PATH -m audit_layer sweep > /dev/null 2>&1
```

To remove it, run `crontab -e` again and delete the line.

## What the repository never does

The repository installs nothing. It never writes to `~/.claude`, a crontab, or `~/Library/LaunchAgents`, and its tests never do either. ForgeCode has no hook here, so its sessions are caught by the schedule.
