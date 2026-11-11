# Acceptance record: turn 1 (child), 11 Nov 2026, Apple M5 (local only)

Binary under test: bin/p3cg sha256 50211edd312d7c225889b1d00e3173ad4288f4624eef1c386e70ecef30661a66
(git 2nd commit; src unchanged since). Actor: child builder. Environment: macOS, Open MPI 5.0.11, Apple clang 21 +
libomp. No cluster access (parent-owned).

| Claim | Basis | What ran / evidence | Status |
|---|---|---|---|
| Serial CG converges, 2D and 3D; error O(h^2) | brief step 1; E12 | validate.py V1/V2: orders 1.998, 2.000 (2D), 1.989, 2.000 (3D) | passed (local) |
| Parallel = serial to rounding, all decompositions, both halo variants, uneven blocks, threads | circuit D4 | V3 max 2.7e-14, V4 max 4.7e-13 (tol 1e-10) | passed (local) |
| Pipelined CG reaches the same converged answer | brief (D2) | V5: diff <= 1.1e-12 vs bound >= 7.7e-8; same iteration counts | passed (local) |
| validate.py qualified: passes the correct build AND refuses the planted bugs | user rule; circuit section 5 | results/validation/local/20261111T163733Z.txt: correct PASS 5/5; bug1 and bug2 REFUSED by V3,V4,V5 | passed (local) |
| Timing gate refuses unqualified binaries | circuit section 5 | gate REFUSED sha 5e5dd83f (modified binary), ALLOWED 50211edd after qualification | passed |
| Run records written by the solver; figures refuse local rows | circuit E10 | run_record.py: 66 local rows well formed; --for-figures REFUSED; selftest QUALIFIED on fixtures | passed on fixtures; real pass example = first cluster row (not run) |
| Run plan covers graded cells; off-plan jobs refused | circuit D5 | check vanda/atlas PASS; selftest: plan without >=256-core weak cells REFUSED; `pbs --job vanda-extra-rerun` REFUSED | passed |
| Plan -> gate -> run -> record -> status -> figure path | brief step 7 | run_plan.py run --plan local --job local-smoke (22 cells x 3) -> status 22/22 -> figures/dev/local_strong.png | passed (local, development data) |
| Offload build | D3 | compiles; host-fallback (target regions on CPU) passes validate --qualify in a scratch results dir; bugs refused | device execution NOT RUN (needs Vanda GPU) |
| PBS scripts | brief step 6 | generated for all vanda/atlas jobs; `bash -n` passes | not run (no cluster access); queue/project/modules/bindings unverified |
| Checks run on old cluster Python | robustness | vermin: minimum Python 3.5 for checks/ | passed (static) |
| Build without CMake | robustness | P3_NO_CMAKE=1 scripts/build.sh in a scratch copy; 2x2 run converges | passed |

Remaining before the promised result: a cluster validation job (binary differs per cluster), the timed jobs, the
first real cluster row (run_record pass example), the GPU run, recalibration of the core-hour model.
