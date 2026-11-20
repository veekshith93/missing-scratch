# Pre-release and camera pilot sign-offs

## Hackathon sign-off

- [x] The corrected factory generates 200 tasks from 20 reserved layouts. The independent geometry solvers agree on accepted scenes. Each layout stays intact in one split.
- [x] Visibility pairs vary mirror angle, camera aim, mirror width or one blocker. The direct-view cases ask about the reflected view. Both mirror endpoints and both ray legs are covered by tests.
- [x] The middle angle and the flattest angle each solve 13/40 corrected repairs. Choosing the less tilted mirror solves 10/20 angle-flip pairs. The repaired suite keeps the correct angle at each of the three ranks.
- [x] The corrected scenes pass a synthetic drift screen. It checks 512 pose-box corners per scene with ±1 mm camera, target and mirror coordinates, ±1 mm mirror width and ±1° yaw and angle. Blocker clearance accounts for up to 1 mm on each center axis and 0.5 mm in radius.
- [x] The CLI can replay archived model replies. Tests cover malformed replies, failure counts, an image that contains an instruction to the model, interrupted responses and a concurrent attempt to resume the same checkpoint.
- [x] A fresh Python environment passed 40 tests, generated an unseen seed, reproduced the corrected suite and re-scored the archived Terra replies. Chrome exercised fresh layouts, reveals, the saved-result view and the calibration requirement.
- [x] The local share candidates passed the common credential pattern and relative-link checks. The dependency audit found no known advisories in the 35 pinned runtime distributions. Recheck the GitHub history when updating the remote.
- [ ] Two people review the exact images and prompts blind. Log each task ID, answer and any missing visual evidence.
- [ ] Measure the tabletop fixture and record agreeing camera frames for both flagship settings, a blocker trial and a repair trial. Repeat the setup and record any disagreement. [Calibration procedure](VALIDATION.md)
- [ ] Run the corrected benchmark with images and a text-only baseline after calibration passes. Review false passes and report model findings against the corrected suite. The archived replies document the original experiment.
- [ ] Check the participant portal’s model and interface requirements, then verify the shared GitHub history, public artifact links, demo recording and deck before submitting.

## Real-world pilot sign-off

- [ ] Observe how a technician confirms that inspection points are covered. Identify the decision owner, the current check, turnaround time, typical rework, and the consequences of a missed point.
- [ ] Agree on representative, partner-approved setups and trusted visibility labels. Capture camera settings, field of view, mirror mount, part position, lighting and relevant drift. Re-create representative fixtures and compare the predicted view with the captured view.
- [ ] Set limits for false passes, false rejects, manual reviews and time per check with the process owner. Record case counts and the disagreement procedure. Treat camera coverage and actual scratch detection as separate measurements. If testing detection, agree on the smallest relevant defect and collect independently labeled good and defective parts across representative conditions. [EMVA camera characterization reference](https://www.emva.org/standards-technology/emva-1288/)
- [ ] Agree on image access, provider sharing, consent, storage location, retention and deletion. Keep partner frames local until the partner approves a destination. Record the people authorized to revoke access, pause the pilot and restore the existing workflow.
- [ ] Run in parallel with the existing check and have a technician decide whether to accept or adjust equipment. Investigate false passes first. Recheck when the camera, lens, mirror mount, lighting or part changes.

## Security and score interpretation

The demo binds to loopback. Model workers receive generated PNGs and a short question, with tools disabled. Camera capture recording is local to the CLI, checks format and size, removes metadata and binds the frame to a task and calibration record. Private captures, calibration and active checkpoints are git-ignored. Test account separation, HTTPS, rate limits and upload handling if a shared service is added. [OWASP ASVS](https://asvs.owasp.org/)

A false pass is an admissible Yes on a hidden reflection. A false reject is an admissible No on a visible reflection. Unparseable, missing and failed requests count against accuracy and require manual review. Reports include the reference-case counts behind each rate.
