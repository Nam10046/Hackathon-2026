# Business case (team parameters)

Data: `/home/claude/ep/Europress_SMART_Material_Value_Engine_v1.0.1/data/competition/public`. Parameters: `../solution/business_case/team_params.yaml` (status: TEAM HYPOTHESIS - not a Europress price, cost or forecast).
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

|   price_per_device_month_eur | price_per_site_month_eur   |   adoption_pct_of_eligible |   eligible_customers |   adopting_customers_expected |   devices_expected |   annual_revenue_eur |   annual_operating_cost_eur |   one_off_onboarding_eur |   year1_contribution_eur |
|-----------------------------:|:---------------------------|---------------------------:|---------------------:|------------------------------:|-------------------:|---------------------:|----------------------------:|-------------------------:|-------------------------:|
|                           15 |                            |                         10 |                   22 |                           2.2 |               24.4 |                 4392 |                        2227 |                     2980 |                     -815 |
|                           15 |                            |                         20 |                   22 |                           4.4 |               48.8 |                 8784 |                        4454 |                     5960 |                    -1630 |
|                           15 |                            |                         35 |                   22 |                           7.7 |               85.4 |                15372 |                        7795 |                    10430 |                    -2853 |
|                           30 |                            |                         10 |                   14 |                           1.4 |                9.9 |                 3564 |                        1147 |                     1615 |                      802 |
|                           30 |                            |                         20 |                   14 |                           2.8 |               19.8 |                 7128 |                        2294 |                     3230 |                     1604 |
|                           30 |                            |                         35 |                   14 |                           4.9 |               34.6 |                12474 |                        4015 |                     5652 |                     2806 |
|                           45 |                            |                         10 |                    7 |                           0.7 |                6   |                 3240 |                         624 |                      860 |                     1756 |
|                           45 |                            |                         20 |                    7 |                           1.4 |               12   |                 6480 |                        1248 |                     1720 |                     3512 |
|                           45 |                            |                         35 |                    7 |                           2.4 |               21   |                11340 |                        2184 |                     3010 |                     6146 |

## What remains unproven

* Willingness to pay at any price (no customer research was done).
* That unnecessary-lift savings are realisable within hygiene, access and peak constraints (Task C shows some savings are harmful).
* That operators would share weighbridge data, accept renegotiation or that a tender succeeds.
* Future models assume a role Europress does not have today (transport procurement, tonne-based service, marketplace).
* That affordable integrated weighing exists at the assumed accuracy (a challenge assumption, not a finding).