# Income and satisfaction in a synthetic survey

## Data

We drew a synthetic sample of 60 respondents with a fixed random seed. Each record gives the respondent's region, age, income, and satisfaction on a five-point scale. The sample was saved once as the raw file and never edited.

Rows with a missing income were dropped. We kept respondents aged 18 or older. Incomes above 250,000 were top-coded to 250,000.

## Methods

We regressed satisfaction on income in thousands by ordinary least squares. The table reports the intercept and the slope to three decimals.

## Results

The slope of satisfaction on income is close to zero.
