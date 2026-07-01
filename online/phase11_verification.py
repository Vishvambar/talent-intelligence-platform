import os
import time
import subprocess
import psutil

# ==============================================================================
# PHASE 11.0: RUNTIME & MEMORY VERIFICATION
# ==============================================================================

def verify_runtime():
    print("Starting Runtime Verification...")
    
    start_time = time.time()
    
    # We use subprocess to isolate the memory footprint
    process = subprocess.Popen(
        ["python3", "online/run_ranking.py"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )
    
    peak_ram = 0
    
    while process.poll() is None:
        try:
            p = psutil.Process(process.pid)
            mem = p.memory_info().rss / (1024 * 1024) # MB
            if mem > peak_ram:
                peak_ram = mem
        except psutil.NoSuchProcess:
            break
        time.sleep(0.1)
        
    end_time = time.time()
    duration = end_time - start_time
    
    stdout, stderr = process.communicate()
    
    print("\n--- INFERENCE OUTPUT ---")
    print(stdout)
    
    if stderr:
        print("--- ERRORS ---")
        print(stderr)
        
    print(f"\n✅ Total Runtime: {duration:.2f} seconds")
    print(f"✅ Peak RAM Usage: {peak_ram:.2f} MB")
    
    if duration > 300:
        print("❌ FAILED: Runtime exceeds 5-minute constraint.")
    else:
        print("✅ PASSED: Runtime is well within 5-minute constraint.")
        
    if peak_ram > 16000:
        print("❌ FAILED: RAM exceeds 16GB constraint.")
    else:
        print("✅ PASSED: RAM is well within 16GB constraint.")

if __name__ == "__main__":
    verify_runtime()
