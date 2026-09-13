You are taking a benchmark. The complete task list is in `testsuites/suite_v3.md`
in this workspace. Read that file in full, including the code corpus embedded
near the end, and solve every task in it.

Rules:

1. Follow the instructions under "How to take this benchmark" and "Output
   format" in that file exactly. Produce one `## <ID>` heading per task, in the
   order given, with nothing else at heading level 2.
2. Use tools only for section C. For every other section, including the whole of
   section L, reason and write without executing anything. Do not extract the
   corpus to files, do not grep or script over it, and do not generate or check
   your number lists with a script.
3. For each answer in section C, start with an `Executed:` line. If you ran code,
   list the exact commands and paste their output verbatim, including any run
   that failed before one succeeded. If you did not, write `Executed: none`.
   Never describe a result you did not actually observe.
4. If you state a count of anything you checked, that number must be the number
   you actually checked. Do not estimate or infer a total.
5. Do not modify, delete, or create files inside `testsuites/`. If you need a
   scratch directory for section C, use `work/`.
6. Do not skip a task. If you cannot complete one, put `SKIPPED: <reason>` under
   its heading.
7. Do not restate the task text, and do not comment on the benchmark itself.

When you are done, write the entire results document to `results.md` in the
workspace root, starting with the line `# Results: <your model name and version>`.
Your results will be scored by a separate grader who sees only that file.
