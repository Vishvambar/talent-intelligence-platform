import os
import subprocess
import hashlib
import time
import polars as pl

def hash_file(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()

def replay_determinism():
    print("Executing Phase 11.25 Submission Replay Audit (10x)...")
    hashes = []
    first_run_df = None

    for i in range(10):
        print(f"Run {i+1}/10...")

        # Run inference
        result = subprocess.run(
            ["python3", "online/run_ranking.py"],
            capture_output=True,
            text=True
        )

        # Hash CSV
        csv_path = "online/submission.csv"
        if not os.path.exists(csv_path):
            log_path = f"online/run_{i+1}_error.log"
            with open(log_path, "w") as f:
                f.write(result.stdout + "\n" + result.stderr)
            raise FileNotFoundError(f"submission.csv not found after run {i+1}!\nLogs saved to {log_path}")

        csv_hash = hash_file(csv_path)
        hashes.append(csv_hash)
        
        current_df = pl.read_csv(csv_path)
        if i == 0:
            first_run_df = current_df
        elif csv_hash != hashes[0]:
            print("\n❌ FAILED: Non-deterministic drift detected on run", i+1)
            print("Finding differences...")
            for idx in range(len(first_run_df)):
                row_a = first_run_df.row(idx)
                row_b = current_df.row(idx)
                if row_a != row_b:
                    print(f"First differing row at index {idx}:")
                    print(f"Run 1: {row_a}")
                    print(f"Run {i+1}: {row_b}")
                    # Score difference specifically
                    diff = abs(row_a[2] - row_b[2]) # Assuming score is at index 2
                    print(f"Candidate ID: {row_a[0]}")
                    print(f"Score Difference: {diff}")
                    break
            raise ValueError("Pipeline is not mathematically deterministic.")

    print("\n--- RESULTS ---")
    unique_hashes = set(hashes)

    if len(unique_hashes) == 1:
        print("✅ PASSED: 10/10 runs produced identical SHA256 hashes.")
        print(f"Hash: {list(unique_hashes)[0]}")

if __name__ == "__main__":
    replay_determinism()
