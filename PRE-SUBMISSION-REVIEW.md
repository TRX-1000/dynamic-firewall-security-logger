# Final pre-submission review

## Verdict

The final archived SDN run supports the core project claims. No new blocker was found for the tested four-host demonstration and benchmark suite. This is a review of the final submitted code/evidence, not a guarantee for untested inputs or a claim that warnings are eliminated. The tested Python and shell source files have not been changed in this review.

## Checks completed

All 84 original submission files were inventoried and read or structurally parsed: 17 Python files, two shell scripts, four Markdown files, one Word document, 20 JSONL files, 28 logs, 11 JSON files and .gitignore. All original manifest checksums matched. Python syntax parsed successfully; the shell scripts use Linux line endings. Code and final results match the user's final uploaded archive byte for byte.

All 3,502 JSONL records parsed successfully (controller-local records, central records, and benchmark samples). The seven logging-validation records pass, all 1,465 controller IDs match central records, and 180/180 benchmark samples succeeded. The 1,857 central records have no duplicate IDs within each run. All 14 warning-associated events were matched to central records. No final controller traceback or recorded OPENFLOW_ERROR was found. Benchmark medians and recovery timings were checked against raw data, not inferred from screenshots.

Nine deterministic tests (four policy and five delivery-check tests) were rerun on the review host and passed. The Ubuntu 20-test completion was reported by the user. No new Mininet execution was performed on this Windows review host. The final suite evidence comes from the user's Ubuntu VM.

## Findings and actions

1. Logging acknowledgement warnings remain. Seven controller and seven application warnings indicate timeout, despite the corresponding records being present centrally. They can influence measured latency. The report already discloses this; do not claim zero warnings, guaranteed delivery, or a fixed firewall performance overhead.

2. Eventlet deprecation and RLock warnings remain. They did not prevent the recorded suite completing, but compatibility with other Python/OS-Ken versions is not established. Keep the demonstrated VM environment for the presentation.

3. tests/controller_smoke.py is a legacy standalone test. It launches osken-manager next to the interpreter and will not work as-is with the current system OS-Ken launcher. It is not one of the 20 unittest-discovered tests. A tests/README.md now labels this explicitly; do not run or cite it as validated on this VM.

4. LOG DELIVERY PASSED has a bounded scope. It compares controller-local IDs with central IDs and checks DISCONNECT counts for centrally observed CONNECT records. It cannot detect an application connection whose CONNECT and DISCONNECT records are both absent, because it has no independent durable application-event ledger. All warning-associated application events in this final run were independently found centrally. The report correctly claims all observed controller events, not universal loss-free application logging.

5. Some live-file reads in topology.py and the concurrency test parse JSONL without excluding a partially written final line. The dedicated logging_checks.py does exclude it. A future unlucky read during an append could raise JSONDecodeError; this did not occur in the submitted run. Changing tested code now would need additional Ubuntu verification, so it is preserved and this robustness limitation is recorded rather than silently patched.

6. The summary is a descriptive comparison, not a statistical-significance test. The final +8.9% goodput difference varies by round and must not be presented as proof that the firewall speeds up traffic. The -5.3% figure from the earlier run is superseded.

7. The run guide assumes the already prepared Ubuntu VM. The guide now lists the installed dependency packages and service prerequisites to help an examiner identify what is needed. This is not a frozen environment or validation of a fresh machine.

## Remaining hand-in items

Fill in the team names, IDs, course/instructor and repository URL in REPORT.docx (and REPORT.md if handing in both). VM CPU/RAM allocation and a machine-readable package inventory are not supplied. The archive contains no dedicated OpenFlow flow-table screenshots or full final 20-test transcript. If your course requires those, add them; existing acceptance logs do not substitute for every rubric-specific artifact. The original grading PDF was not available in this review, so complete rubric compliance cannot be certified.

The Word document's text, tables and XML structure were checked against the report. Page rendering could not be completed because this host has no available LibreOffice/Word renderer. Open REPORT.docx in Word or LibreOffice and check page breaks/table layout before submitting. This is a presentation check, not another benchmark run.

## File coverage

- controller.py, policy.py: classification, flow priorities, threshold/window, expiry, source binding and queue use reviewed.
- events.py, logger_server.py, server.py, client.py: framing, timeouts, persistence acknowledgement, concurrency and measurement definitions reviewed.
- topology.py, logging_checks.py: startup order, acceptance checks, per-run evidence, delivery checks and cleanup reviewed.
- controller_launcher.py, run-controller.sh, run-suite.sh: runtime mode, controller lifecycle, suite ordering and result paths reviewed.
- summarize.py, view_logs.py: raw-data selection, median calculations, output and parsing reviewed.
- local_lab.py, local_firewall.py: portable proxy behavior reviewed; not used as SDN performance evidence.
- tests/test_project.py, tests/test_local.py, tests/test_logging_checks.py: all 20 test cases reviewed; test scope distinguished from actual SDN acceptance.
- tests/controller_smoke.py: legacy launcher dependency identified and documented.
- README.md, RUN-GUIDE.md, REPORT.md, REPORT.docx: claims, instructions, limitations and missing hand-in details reviewed.
- results/: all final raw files, logs, validation files, recovery/demo files and summary checked.
- VERIFICATION.json, SHA256SUMS.json, .gitignore: audit content, hashes and evidence inclusion checked.

The reviewed ZIP adds these notes and test guidance, updates run-guide prerequisites and refreshes hashes. Application source and measured results remain identical to the validated final archive.
