---
name: Bug report
about: Report something in kivyforge that doesn't work
title: ''
labels: 'bug'
assignees: ''

---

<!--
Please check the open issues first:
https://github.com/ElliotGarbus/kivyforge/issues

If a build fails, the troubleshooting guide may already explain it:
https://elliotgarbus.github.io/kivyforge/troubleshooting/

Check that what you paste holds no passwords, tokens, or private paths.
-->

**Versions**

* kivyforge (`kivyforge --version`):
* Target platform (`-p`):
* Build host and its OS version:
* Device or emulator and its OS version, if the problem is at run time:

**Describe the bug**
// REPLACE ME: What happened, and what you expected to happen instead.

**To reproduce**
// REPLACE ME: The exact `kivyforge ...` commands you ran, in order.

**`kivyforge doctor -p PLATFORM`**
```
// REPLACE ME: The output for the target you are building.
```

**Build log**
<!-- `kivyforge COMMAND > build.log 2>&1` captures all of it. For Android, add -v. -->
```
// REPLACE ME: The output of the failing command, including the error.
```

**`pyproject.toml`**
```toml
// REPLACE ME: Your configuration, or a link to a small project that reproduces the problem.
```

**Additional context**
Anything else that might help, such as screenshots of an Xcode error or the app's log from the device.
