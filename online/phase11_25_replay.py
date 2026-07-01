import os
import subprocess
import hashlib
import time

def hash_file(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()

def replay_determinism():
    print("Executing Phase 11.25 Submission Replay Audit (10x)...")
    
    hashes = []
    
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
            raise FileNotFoundError(f"submission.csv not found after run {i+1}! Logs saved to {log_path}")
            
        csv_hash = hash_file(csv_path)
        hashes.append(csv_hash)
        
    print("\n--- RESULTS ---")
    unique_hashes = set(hashes)
    
    if len(unique_hashes) == 1:
        print("✅ PASSED: 10/10 runs produced identical SHA256 hashes.")
        print(f"Hash: {list(unique_hashes)[0]}")
    else:
        print("❌ FAILED: Non-deterministic drift detected!")
        print(f"Found {len(unique_hashes)} unique hashes.")
        for h in unique_hashes:
            print(h)
        raise ValueError("Pipeline is not mathematically deterministic.")

if __name__ == "__main__":
    replay_determinism()
