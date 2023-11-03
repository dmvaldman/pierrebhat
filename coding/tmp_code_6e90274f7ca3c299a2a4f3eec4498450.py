import yfinance as yf

# Define the ticker symbol
tickerSymbol1 = 'META'
tickerSymbol2 = 'TSLA'

# Get data on this ticker
tickerData1 = yf.Ticker(tickerSymbol1)
tickerData2 = yf.Ticker(tickerSymbol2)

# Get the historical prices for this ticker
tickerDf1 = tickerData1.history(period='1d', start='2022-1-1', end='2022-12-31')
tickerDf2 = tickerData2.history(period='1d', start='2022-1-1', end='2022-12-31')

# See the opening price at the start of the year
start_price_META = tickerDf1['Open'][0]
start_price_TSLA = tickerDf2['Open'][0]

# See the closing price now
end_price_META = tickerDf1['Close'][-1]
end_price_TSLA = tickerDf2['Close'][-1]

# Calculate the YTD gain
YTD_gain_META = ((end_price_META - start_price_META) / start_price_META) * 100
YTD_gain_TSLA = ((end_price_TSLA - start_price_TSLA) / start_price_TSLA) * 100

print("META's YTD gain is: ", YTD_gain_META, "%")
print("TESLA's YTD gain is: ", YTD_gain_TSLA, "%")