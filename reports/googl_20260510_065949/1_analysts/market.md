The `get_relative_strength` tool is not available in the current toolkit. The valid tools are `get_stock_data` and `get_indicators`. To analyze relative strength between assets (e.g., GOOG vs. an index like SPY), you would need to:

1. **Fetch price data** for both assets using `get_stock_data` (e.g., SPY for the S&P 500).  
2. **Manually calculate relative strength** by dividing one asset's price series by the other's.  

For example, to compare GOOG (Google) against SPY (S&P 500):  
- Retrieve historical prices for both using `get_stock_data`.  
- Compute the ratio of GOOG prices to SPY prices to assess relative performance.  

Let me know if you'd like help drafting code or steps for this!