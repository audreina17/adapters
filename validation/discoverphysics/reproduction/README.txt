DiscoverPhysics: reproduce the selected parity comparisons

These files reproduce the execution settings behind the reported Gravity,
Yukawa, Oscillator and Hubble comparisons. There are three repetitions per side.
Gravity uses seeds 0/1. Yukawa uses 2/3; Oscillator and Hubble use 0/1.
Do not combine Gravity with the other worlds into a single parity score:
the latter use a persistent law-execution worker and a four-seed task universe.

The pinned official upstream source is unchanged. The original-side entry point
sets the judge output budget and request timeout, and installs streamed inference.
The Harbor-side agent and exact task assets are copied from the recorded runs.
Only local session orchestration is replaced by run.py. Source checksums and
settings are in manifest.json. A floating provider model ID cannot recreate
an immutable historical model snapshot.

Requirements: Docker, Python 3.13, and Harbor at commit
3c82380859d187957cfd5cd64802b076d9779550. For example:
  uv venv --python 3.13
  uv pip install "harbor @ git+https://github.com/harbor-framework/harbor.git@3c82380859d187957cfd5cd64802b076d9779550"
Use your own OPENAI_API_KEY and OPENAI_BASE_URL. No credentials are included.
The recorded endpoint was https://api.inference.wandb.ai/v1 and the model was
zai-org/GLM-5.3-Flash for both discovery and judging.

Examples, run from this directory with the environment activated:
  python run.py original gravity --seed 0 --run 1
  python run.py harbor gravity --seed 0 --run 1
  python run.py original yukawa --seed 2 --run 1
  python run.py harbor yukawa --seed 2 --run 1
Repeat for the listed seeds and runs 1, 2 and 3. Modal is optional for the
Harbor side via --environment modal; cloud credentials must be configured locally.

Outputs are written under outputs/{side}/{world}/seed-{seed}/run-{run}.
Existing outputs are never overwritten. Preserve failed attempts and statuses;
new outputs must not be described as the original historical runs.

This package contains only the comparisons selected for the final evidence set.
Selection was retrospective; other explored configurations were not included.
That limitation and the existing attempt records remain in the evidence report.
An all-failure match has limited power to demonstrate implementation equivalence.

Offline checks cover source identity, syntax, task assets, and configuration.
The new portable launcher has not itself been rerun against a paid model.
