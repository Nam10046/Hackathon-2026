# Business case (team parameters)

Data: `/home/claude/ep/Europress_SMART_Material_Value_Engine_v1.0.1/data/competition/public`. Parameters: `../solution/business_case/team_params_outcome.yaml` (status: TEAM HYPOTHESIS (OUTCOME PRICING) - not a Europress price, cost or forecast).
**Every number is a synthetic-world estimate under the team's own hypothetical parameters; it is not market evidence, not a Europress price or cost and not a demonstrated saving.** Europress is currently not a party to waste transport or treatment; tariffs, processing fees and material credits are agreed between the customer and the waste operator.

## Identified value by lever (sum over customers, annualised, before realisation)

| lever                |   identified_eur |   realisation_share |
|:---------------------|-----------------:|--------------------:|
| billing_review       |            44339 |                 0.6 |
| over_servicing       |           231625 |                 0.3 |
| contamination        |           114002 |                 0.2 |
| contract_review      |           241692 |                 0.3 |
| operator_performance |           406129 |                 0.3 |
| operator_tendering   |           145670 |                 0.4 |

## By fleet segment

| segment   |   customers |   devices |   median_spend |   median_identified |   median_realisable |
|:----------|------------:|----------:|---------------:|--------------------:|--------------------:|
| 16+       |           8 |       238 |       305886   |             92580.9 |             28101.4 |
| 2-5       |          32 |        94 |        27598.8 |              3541.3 |              1167.8 |
| 6-15      |          12 |       115 |        94735.7 |             16789.1 |              5318   |

## Portfolio scenarios (price x adoption)

| price_per_device_month_eur   | price_per_site_month_eur   |   adoption_pct_of_eligible |   eligible_customers |   adopting_customers_expected |   devices_expected |   annual_revenue_eur |   annual_operating_cost_eur |   one_off_onboarding_eur |   year1_contribution_eur |
|:-----------------------------|:---------------------------|---------------------------:|---------------------:|------------------------------:|-------------------:|---------------------:|----------------------------:|-------------------------:|-------------------------:|
|                              |                            |                         10 |                   52 |                           5.2 |               44.7 |                    0 |                        4642 |                     6395 |                   -11037 |
|                              |                            |                         20 |                   52 |                          10.4 |               89.4 |                    0 |                        9283 |                    12790 |                   -22073 |
|                              |                            |                         35 |                   52 |                          18.2 |              156.4 |                    0 |                       16246 |                    22382 |                   -38628 |

## What remains unproven

* Willingness to pay at any price (no customer research was done).
* That unnecessary-lift savings are realisable within hygiene, access and peak constraints (Task C shows some savings are harmful).
* That operators would share weighbridge data, accept renegotiation or that a tender succeeds.
* Future models assume a role Europress does not have today (transport procurement, tonne-based service, marketplace).
* That affordable integrated weighing exists at the assumed accuracy (a challenge assumption, not a finding).