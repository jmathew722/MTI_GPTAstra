| scenario | expected | result | actual |
|---|---|---|---|
| unicode_and_spaces_in_path | part completes or needs review, files exist | PASS | review_required; artifacts=['dimension_coverage.json', 'drawing.pdf', 'drawing.slddrw', 'drawing_plan.json'] |
| duplicate_basenames | two distinct ids, both processed, outputs in separate folders | PASS | ids=['Dup', 'Dup-2'] |
| corrupt_file_and_assembly_and_one_failure_in_a_batch | assembly rejected up front; corrupt part fails with a clear message; the good parts still complete | PASS | states={'Dup': 'review_required', 'corrupt': 'failed', 'Dup-2': 'review_required'}; rejected=['thing.SLDASM']; corrupt_error=CadError: SOLIDWORKS could not open |
| sldworks_still_healthy_after_a_corrupt_file | the same session still builds a drawing | PASS | 33.5.0 |
| unwritable_output_folder | the part fails with an output-folder message, nothing half-published | PASS | failed: CadError: The output folder for this part could not be created or written (FileExistsError). Check the output location and its permissions. |
| cancellation_between_parts | the first part is published; the rest are canceled; nothing corrupt | PASS | states=['review_required', 'canceled', 'canceled'] |
| profile_metric_a3_third_angle | drawing created on A3 with the right projection and units | PASS | review_required; projection=third; units=mm; scale=1:1 |
| profile_iso_first_angle_a3 | drawing created on A3 with the right projection and units | PASS | review_required; projection=first; units=mm; scale=1:1 |
| part_already_open_by_the_user | the job runs on a hashed working copy, records a warning, and the user's document stays open and untouched | FAIL | failed; warned=True; still_open=True |
| source_hash_unchanged | the source part is byte-identical after the job and the manifest says so | PASS | sha256=d04499e690cd2022... |
