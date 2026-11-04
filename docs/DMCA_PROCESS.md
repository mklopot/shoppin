# DMCA Standard Operating Procedure (SOP) & Admin Runbook

**Service:** `recipe.klopot.tech`  
**Governing Statute:** 17 U.S.C. § 512 (*Digital Millennium Copyright Act*) & 37 C.F.R. § 201.38  
**Designated Agent Title:** DMCA Designated Agent  
**Designated Agent Email:** `dmca@recipe.klopot.tech` (fallback: `support@recipe.klopot.tech`)  
**Designated Agent Jurisdiction:** Denver, Colorado, United States  
**Last Updated:** November 2026  

---

## 1. Overview and Safe Harbor Protection

To maintain statutory safe harbor immunity from copyright liability under **17 U.S.C. § 512(c)**, `recipe.klopot.tech` must adhere strictly to the notice-and-takedown protocol, maintain an accurate repeat infringer tracking log, and register its Designated Agent with the U.S. Copyright Office.

This runbook instructs the system administrator and DMCA Designated Agent on receiving, verifying, executing, and logging DMCA takedown notices and counter-notices.

---

## 2. Step 1: Receiving and Validating Takedown Notices

When an email arrives at `dmca@recipe.klopot.tech` claiming copyright infringement, review it against the **6 statutory requirements of 17 U.S.C. § 512(c)(3)**:

| # | Statutory Requirement | Verification Check |
|---|-----------------------|--------------------|
| 1 | **Physical or Electronic Signature** | Must contain the full name, electronic signature, or scanned physical signature of the copyright owner or authorized representative. |
| 2 | **Identification of Copyrighted Work** | Must identify the original copyrighted work (e.g. title of original cookbook, URL of original blog post, or registration number). |
| 3 | **Identification of Infringing Material** | Must provide specific URLs or recipe identifiers on `recipe.klopot.tech` sufficient for the agent to locate the material. |
| 4 | **Complainant Contact Information** | Must provide full legal name, physical mailing address, telephone number, and email address. |
| 5 | **Good Faith Belief Statement** | Must include: *"I have a good faith belief that use of the material in the manner complained of is not authorized by the copyright owner, its agent, or the law."* |
| 6 | **Penalty of Perjury Statement** | Must include: *"The information in this notification is accurate, and under penalty of perjury, I am authorized to act on behalf of the owner of an exclusive right that is allegedly infringed."* |

### Handling Incomplete or Defective Notices
- If a notice is missing any of the 6 requirements above, **do not ignore it**.
- Reply promptly (within 24 hours) using the following template:
  > *"Thank you for contacting recipe.klopot.tech. Under 17 U.S.C. § 512(c)(3), an effective copyright takedown notice must contain [list missing elements, e.g., statement under penalty of perjury and exact URL on our service]. Please provide the missing information so we may process your request expeditiously."*

---

## 3. Step 2: Content Disabling & Quarantine Procedure

Once a valid notice is confirmed:

### A. Immediate Action in Django Admin
1. Navigate to `/admin/recipes/recipe/` in your browser.
2. Search for the recipe by ID, name, or slug.
3. Edit the recipe:
   - Uncheck **"Is public"** (`is_public = False`).
   - If the entire recipe is infringing, check **"Is locked from public"** and append `[DMCA TAKEDOWN - Case #{NoticeID}]` to internal notes.
   - If only an image is infringing, clear or replace the image file.
4. Save the record.

### B. Command-Line Alternative (Django Shell)
```bash
python manage.py shell
```
```python
from apps.recipes.models import Recipe
from apps.core.models import UserDMCAProfile

# Locate recipe
recipe = Recipe.objects.get(id=123)

# Quarantine content
recipe.is_public = False
recipe.save(update_fields=["is_public"])

# Record strike on the author
if recipe.created_by:
    profile, _ = UserDMCAProfile.objects.get_or_create(user=recipe.created_by)
    strikes = profile.record_strike(
        notice_id="DMCA-2026-001",
        affected_urls=[recipe.get_absolute_url()],
        notes="Infringing text copied verbatim from complainant publication.",
    )
    print(f"User {recipe.created_by.username} now has {strikes} strikes.")
```

---

## 4. Step 3: Notifying the Alleged Infringer

Under 17 U.S.C. § 512(g)(2)(A), the service provider must take reasonable steps promptly to notify the subscriber that it has removed or disabled access to the material.

Send an email to the user associated with the removed content:

```text
Subject: [recipe.klopot.tech] Important: Content Removed Under DMCA Copyright Notice (Notice #{NoticeID})

Dear {Username},

We are writing to inform you that content you submitted to recipe.klopot.tech has been removed or disabled in response to a formal copyright infringement notification received pursuant to the Digital Millennium Copyright Act (17 U.S.C. § 512).

Details of the Takedown:
- Notice Reference: #{NoticeID}
- Affected Content / URL: {RecipeURL}
- Complaining Party: {ComplainantName / Organization}
- Copyright Strike Status: You currently have {CurrentStrikes} of 3 allowable copyright strikes.

Repeat Infringer Policy:
Under 17 U.S.C. § 512(i) and our Terms of Service, any user account that accumulates three (3) copyright strikes will be permanently terminated.

Counter-Notification Procedure:
If you believe in good faith that this material was removed as a result of mistake or misidentification (e.g., you own the material, have a valid license, or your use constitutes non-infringing fair use), you have the statutory right under 17 U.S.C. § 512(g)(3) to submit a formal Counter-Notification.

To be valid, your counter-notification must be in writing and sent to dmca@recipe.klopot.tech with:
1. Your physical or electronic signature.
2. Identification of the material that was removed and the URL where it appeared before removal.
3. A statement under penalty of perjury: "I have a good faith belief that the material was removed or disabled as a result of mistake or misidentification of the material."
4. Your full name, physical mailing address, and telephone number.
5. A statement consenting to the jurisdiction of the Federal District Court for your judicial district (or Denver County, Colorado, if you reside outside the United States), and agreeing to accept service of process from the complaining party.

Upon receipt of a valid counter-notification, we will forward a copy to the complaining party. If they do not file a federal court action within 10 to 14 business days, the removed material will be restored and the associated copyright strike will be cleared.

For more information, please review our DMCA Policy at https://recipe.klopot.tech/dmca/.

Sincerely,
DMCA Designated Agent
recipe.klopot.tech
dmca@recipe.klopot.tech
```

---

## 5. Step 4: Handling Counter-Notifications

If the user submits a counter-notification:

1. **Verify 512(g)(3) Requirements:**
   - Physical or electronic signature.
   - Identified content and prior location.
   - Penalty of perjury statement.
   - Contact info + Federal court jurisdiction consent and service of process acceptance.

2. **Forward to Complainant:**
   - Forward the complete counter-notification to the original complaining party within 24–48 hours.
   - State clearly:
     > *"Enclosed is a formal DMCA counter-notification submitted under 17 U.S.C. § 512(g)(3). Under federal law, recipe.klopot.tech will restore the removed material and clear the strike within 10 to 14 business days from today unless you provide us with evidence that you have filed a federal court action seeking a court order to restrain the user from engaging in infringing activity."*

3. **Track the 10–14 Business Day Window:**
   - Set a calendar reminder for 10 business days and 14 business days from delivery.
   - **Scenario A (Complainant provides court filing):** Keep content disabled pending judicial resolution.
   - **Scenario B (No court filing received within 14 business days):**
     - Re-enable the recipe (`recipe.is_public = True` or restore content).
     - Remove the strike in Django Admin or shell:
       ```python
       profile.remove_strike(reason="Uncontested counter-notice expired after 14 business days.")
       ```
     - Notify the user that their content has been restored.

---

## 6. Step 5: Repeat Infringer Policy Enforcement

Pursuant to **17 U.S.C. § 512(i)(1)(A)**:

- **Strike 1:** Content disabled, written warning issued, 1 strike logged.
- **Strike 2:** Content disabled, final warning issued, 2 strikes logged.
- **Strike 3:** Account designated as repeat infringer:
  - `profile.is_banned = True` (automatically applied by `record_strike()`).
  - User is blocked by middleware and views from creating, editing, or importing recipes.
  - Active sessions revoked.
  - Public recipes set to private.

---

## 7. Step 6: U.S. Copyright Office Registration Maintenance

Federal law requires that the Designated Agent be registered in the **U.S. Copyright Office Online Directory of Designated Agents**:

1. Log in to [https://dmca.copyright.gov/](https://dmca.copyright.gov/).
2. Service Provider Legal Entity: `recipe.klopot.tech`
3. Alternate Names: `Recipe`, `recipe.klopot.tech`
4. Designated Agent:
   - Title/Position: `DMCA Designated Agent`
   - Email: `dmca@recipe.klopot.tech`
   - Address: Denver, Colorado mailing address
5. Renewal Requirement: Registrations expire every **3 years** and require a $6 renewal fee to remain legally effective. Set a calendar reminder to renew before expiration.
