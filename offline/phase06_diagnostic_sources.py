import polars as pl

INPUT_FILE = "/kaggle/working/artifacts/retrieval_top_10000.parquet"

def run_diagnostic():
    print(f"Loading {INPUT_FILE}...")
    df = pl.read_parquet(INPUT_FILE)
    
    k_values = [100, 500, 3000, 10000]
    
    for k in k_values:
        print(f"\n=== Top {k} Retrieval Sources ===")
        
        # Extract top k candidates
        top_k = df.head(k)
        
        # Count the retrieval sources
        counts = top_k["retrieval_source"].value_counts().sort("count", descending=True)
        
        for row in counts.iter_rows():
            source = row[0]
            count = row[1]
            pct = (count / k) * 100
            print(f"  {source:<12} : {count:<5} ({pct:.1f}%)")

if __name__ == "__main__":
    run_diagnostic()
