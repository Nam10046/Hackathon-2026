# Business case (team parameters)

Data: `/home/claude/ep/Europress_SMART_Material_Value_Engine_v1.0.1/data/competition/public`. Parameters: `../solution/business_case/team_params_future.yaml` (status: TEAM HYPOTHESIS (FUTURE MODELS ON) - not a Europress price, cost or forecast).
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
| 16+       |           8 |       238 |       305886   |             92580.9 |             35866.6 |
| 2-5       |          32 |        94 |        27598.8 |              3541.3 |              1680.7 |
| 6-15      |          12 |       115 |        94735.7 |             16789.1 |              7181.8 |

## Portfolio scenarios (price x adoption)

|   price_per_device_month_eur | price_per_site_month_eur   |   adoption_pct_of_eligible |   eligible_customers |   adopting_customers_expected |   devices_expected |   annual_revenue_eur |   annual_operating_cost_eur |   one_off_onboarding_eur |   year1_contribution_eur |
|-----------------------------:|:---------------------------|---------------------------:|---------------------:|------------------------------:|-------------------:|---------------------:|----------------------------:|-------------------------:|-------------------------:|
|                           15 |                            |                         10 |                   31 |                           3.1 |               31.8 |                13916 |                        3014 |                     4070 |                     6831 |
|                           15 |                            |                         20 |                   31 |                           6.2 |               63.6 |                27831 |                        6029 |                     8140 |                    13662 |
|                           15 |                            |                         35 |                   31 |                          10.8 |              111.3 |                48705 |                       10550 |                    14245 |                    23909 |
|                           30 |                            |                         10 |                   17 |                           1.7 |               16.3 |                11416 |                        1598 |                     2175 |                     7642 |
|                           30 |                            |                         20 |                   17 |                           3.4 |               32.6 |                22832 |                        3197 |                     4350 |                    15285 |
|                           30 |                            |                         35 |                   17 |                           5.9 |               57   |                39955 |                        5594 |                     7612 |                    26748 |
|                           45 |                            |                         10 |                   11 |                           1.1 |                8.4 |                 8178 |                         931 |                     1300 |                     5947 |
|                           45 |                            |                         20 |                   11 |                           2.2 |               16.8 |                16356 |                        1862 |                     2600 |                    11893 |
|                           45 |                            |                         35 |                   11 |                           3.8 |               29.4 |                28623 |                        3259 |                     4550 |                    20814 |

## What remains unproven

* Willingness to pay at any price (no customer research was done).
* That unnecessary-lift savings are realisable within hygiene, access and peak constraints (Task C shows some savings are harmful).
* That operators would share weighbridge data, accept renegotiation or that a tender succeeds.
* Future models assume a role Europress does not have today (transport procurement, tonne-based service, marketplace).
* That affordable integrated weighing exists at the assumed accuracy (a challenge assumption, not a finding).