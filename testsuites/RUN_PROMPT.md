You are taking a benchmark. The complete task list is in `suite_v2.md`
in this workspace. Read that file in full, including the code corpus embedded at
the end, and solve every task in it.

Rules:

1. Follow the instructions under "How to take this benchmark" and "Output
   format" in that file exactly. Produce one `## <ID>` heading per task, in the
   order given, with nothing else at heading level 2.
2. Use tools only for section I. For every other section, reason and write
   without executing anything.
3. For each answer in section I, start with an `Executed:` line. If you ran
   code, list the exact commands and paste their output verbatim. If you did
   not, write `Executed: none`. Never describe a test result you did not
   actually observe.
4. Do not modify, delete, or create files inside `testsuites/` workspace. If you need a
   scratch directory for section I, use `work/`.
5. Do not skip a task. If you cannot complete one, put `SKIPPED: <reason>`
   under its heading.
6. Do not restate the task text, and do not comment on the benchmark itself.

When you are done, write the entire results document to `results.md` in the
workspace root, starting with the line `# Results: <your model name and version>`.
Your results will be scored by a separate grader who sees only that file.
