from pathlib import Path
import argparse
import json
import os
import subprocess
import sys

ROOT = Path(__file__).resolve().parent

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("side", choices=["original", "harbor"])
    parser.add_argument("world", choices=["gravity", "yukawa", "oscillator", "hubble"])
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--run", type=int, choices=[1, 2, 3], required=True)
    parser.add_argument("--environment", choices=["docker", "modal"], default="docker")
    args = parser.parse_args()
    manifest = json.loads((ROOT / "manifest.json").read_text())
    settings = manifest["worlds"][args.world]
    if args.seed not in settings["seeds"]:
        parser.error("Seed is outside this comparison's selected task set")
    if not os.environ.get("OPENAI_API_KEY"):
        parser.error("Set OPENAI_API_KEY before running")
    os.environ.setdefault("OPENAI_BASE_URL", "https://api.inference.wandb.ai/v1")
    os.environ["DISCOVERPHYSICS_JUDGE_MODEL"] = manifest["judge_model"]
    root = ROOT / args.world
    output = ROOT / "outputs" / args.side / args.world / f"seed-{args.seed}" / f"run-{args.run}"
    if output.exists():
        parser.error("Output already exists; preserve it before launching another attempt")
    output.mkdir(parents=True)
    if args.side == "original":
        image = f"discoverphysics-original-{args.world}"
        subprocess.run(["docker", "build", "-f", str(root / "Dockerfile.original"), "-t", image, str(root)], check=True)
        command = ["docker", "run", "--rm", "--cpus", "4", "--memory", "8g", "-e", "OPENAI_API_KEY", "-e", "OPENAI_BASE_URL", "-v", f"{output}:/evidence", image,
                   "--world", args.world, "--model", manifest["model"], "--judge-model", manifest["judge_model"], "--engine", "nbody", "--noise-std", str(0.05 * settings["world_variance"] ** 0.5), "--noise-seed", str(args.seed), "--max-rounds", "16", "--max-tokens", "131072", "--output", "/evidence/result.json", "--store_output", "/evidence/transcript"]
        subprocess.run(command, check=True)
    else:
        config = {"job_name": "harbor", "jobs_dir": str(output), "n_attempts": 1, "n_concurrent_trials": 1, "retry": {"max_retries": 0},
                  "environment": {"type": args.environment, "delete": True},
                  "agents": [{"import_path": "adapters.discoverphysics.discoverphysics_parity_agent:DiscoverPhysicsOpenAIParityAgent", "model_name": "openai/" + manifest["model"], "override_timeout_sec": 72000, "kwargs": {"max_tokens": 131072}}],
                  "tasks": [{"path": str(root / "tasks" / f"{args.world}__seed-{args.seed}")}]}
        if args.environment == "modal":
            config["environment"]["kwargs"] = {"modal_vm_runtime": True, "sandbox_timeout_secs": 86400}
        path = output / "job.json"
        path.write_text(json.dumps(config, indent=2) + "\n")
        env = dict(os.environ)
        env["PYTHONPATH"] = str(root) + os.pathsep + env.get("PYTHONPATH", "")
        subprocess.run(["harbor", "run", "-c", str(path)], cwd=root, env=env, check=True)

if __name__ == "__main__":
    main()
