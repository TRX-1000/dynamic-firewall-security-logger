# Test scope

Run the 20 current tests from the project root:

```bash
python3 -m unittest discover -s tests -v
```

These comprise four policy tests and six socket tests in test_project.py, five portable proxy tests in test_local.py, and five persistence-check tests in test_logging_checks.py. Proxy tests are not Mininet results. The outage test intentionally emits a logger warning.

controller_smoke.py is a separate legacy test using osken-manager from the interpreter directory. It is not discovered by the command above, is not compatible as-is with the current system OS-Ken launcher, and was not rerun on this VM. Use the actual Mininet demo/suite for the submitted OpenFlow evidence. This file is retained for provenance, not advertised as a supported current command.
