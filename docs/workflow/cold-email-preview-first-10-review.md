# Cold Email Preview Review - First 10 Eligible Rows

Generated: 2026-05-06 09:46 
Mode: read-only preview; no NocoDB patch; no email send.

| row_id | company | pressure | profile | profile_confidence | greeting_type | greeting_ok | used_first_name | funding | flags | batch wording | signal wording | duplicate vendor | cluttered | send ready |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 273 | Amaris B. Clinic | hia_regulatory | aesthetic_medical | high | named_person | True | True | verified_match | `["copy_qa_mode"]` | False | False | False | False | False |
| 274 | Amazing Hearing Group | hia_regulatory | hearing_care | high | named_person | True | True | verified_match | `["copy_qa_mode"]` | False | False | False | False | False |
| 275 | Amber Family Clinic | hia_regulatory | family_gp | high | generic_team | True | False | verified_match | `["copy_qa_mode"]` | False | False | False | False | False |
| 276 | Amber Compounding Pharmacy | hia_regulatory | pharmacy | high | named_person | True | True | verified_match | `["funding_needs_review","copy_qa_mode"]` | False | False | False | False | False |
| 277 | American International Clinic Singapore | hia_regulatory | family_gp | high | named_person | True | True | verified_match | `["copy_qa_mode"]` | False | False | False | False | False |
| 279 | Amoy Street Dental | hia_regulatory | dental | high | named_person | True | True | verified_match | `["copy_qa_mode"]` | False | False | False | False | False |
| 280 | AMP Lab | pdpa_safeguards |  |  | named_person | True | True | needs_review | `["funding_needs_review","low_trigger_confidence","funding_not_verified","copy_qa_mode"]` | False | False | False | False | False |
| 282 | An Dental | hia_regulatory | dental | high | generic_team | True | False | possible_match | `["funding_needs_review","funding_not_verified","copy_qa_mode"]` | False | False | False | False | False |
| 283 | Andrea's Digestive, Colon, Liver and Gallbladder Clinic | hia_regulatory | specialist_led | high | generic_team | True | False | verified_match | `["copy_qa_mode"]` | False | False | False | False | False |
| 284 | AN Medical Clinic | hia_regulatory | family_gp | high | generic_team | True | False | verified_match | `["copy_qa_mode"]` | False | False | False | False | False |

## Notes

- `batch wording` scans final email bodies only.
- `signal wording` scans final email bodies for internal signal language.
- `copy_qa_mode` forces `email_send_ready=false`.
