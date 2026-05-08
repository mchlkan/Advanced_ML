# Kleinanzeigen mobile-API listing-create reference

Distilled from a mitmproxy capture of the KA Android app v2026.19.1 walking
the full "Anzeige aufgeben" flow on a COMMERCIAL account
(`poster-type=COMMERCIAL`). Capture file at `captures/ka/listing_create.bin`
(gitignored — contains live JWT + refresh_token).

User_id: integer, embedded in the JWT's
`https://www.kleinanzeigen.de/user_id` claim. Use this as the path
parameter for ads.json submissions.

---

## Auth tiers

| Tier | Endpoint host | Auth | Purpose |
|---|---|---|---|
| **Tier 1** | `api.kleinanzeigen.de` | `Authorization: Basic YW5kcm9pZDpUYVI2MHBFdHRZ` (`android:TaR60pEttY`) | Photo upload, public reads. Same hardcoded creds as the scrape path |
| **Tier 2** | `api.kleinanzeigen.de` (write paths) | Tier-1 Basic **plus** `x-ecg-authorization-user: email=<email>,access=<JWT>` | Listing submit, user-owned data (ads, profile) |

The Tier-2 JWT is the access_token from `POST login.kleinanzeigen.de/oauth/token`.
1-hour TTL. Refresh via `grant_type=refresh_token` (single-use refresh token).

---

## Login (Auth0 + Akamai BMP + MFA SMS) — capture-once only

The login path is heavily protected and **not feasible to drive
programmatically without a real browser**. Sequence (in capture order):

```
GET  /authorize?response_type=code&client_id=uV5j90my…&redirect_uri=login.kleinanzeigen.de/android/com.ebay.kleinanzeigen/callback&code_challenge=…
GET  /akam/13/472486c4                              # Akamai BMP sensor JS
GET  /62Zis4ERY/H/.../ElGkgB                        # Akamai BMP challenge
POST /akam/13/pixel_472486c4                        # Akamai sensor POST
GET  /u/login/password                              # password page
POST /u/login/password                              # submit creds
GET  /u/mfa-sms-challenge
POST /u/mfa-sms-challenge                           # submit SMS code
GET  /authorize/resume   (×2)                       # OAuth callback
POST /oauth/token                                   # exchange code → tokens
GET  /userinfo
```

`POST /oauth/token` request body (JSON):

```json
{
  "client_id": "uV5j90myVPc2XzEOFuWUD2At17OACEGQ",
  "grant_type": "authorization_code",
  "code": "<one-shot code from /authorize/resume>",
  "redirect_uri": "https://login.kleinanzeigen.de/android/com.ebay.kleinanzeigen/callback",
  "code_verifier": "<PKCE verifier matching the code_challenge>"
}
```

Response (200):

```json
{
  "access_token": "<RS256 JWT, kid=8Pgiq-F9XDD6krbCllXor>",
  "refresh_token": "<opaque ~43-char string>",
  "id_token": "<RS256 JWT with profile claims>",
  "scope": "openid profile email offline_access urn:ebay-kleinanzeigen:user",
  "expires_in": 3600,
  "token_type": "Bearer"
}
```

`access_token` payload (decoded):

```json
{
  "https://www.kleinanzeigen.de/user_id": 45852425,
  "https://www.kleinanzeigen.de/user_uuid": "3fd1d48b-…",
  "iss": "https://login.kleinanzeigen.de/",
  "sub": "auth0|3fd1d48b-…",
  "aud": ["api://default", "https://kleinanzeigen.kleinanzeigen-prod.auth0app.com/userinfo"],
  "scope": "openid profile email offline_access urn:ebay-kleinanzeigen:user",
  "azp": "uV5j90my…",
  "iat": …, "exp": …
}
```

### Refresh (no Akamai, no MFA)

```http
POST https://login.kleinanzeigen.de/oauth/token
Content-Type: application/json
User-Agent: Kleinanzeigen Android 2026.19.1
auth0-client: eyJuYW1lIjoiQXV0aDAuQW5kcm9pZCIsImVudiI6eyJhbmRyb2lkIjoiMjYifSwidmVyc2lvbiI6IjMuMTUuMCJ9

{
  "client_id": "uV5j90myVPc2XzEOFuWUD2At17OACEGQ",
  "grant_type": "refresh_token",
  "refresh_token": "<previous refresh_token>"
}
```

Returns a fresh access_token + refresh_token (rotated). **Refresh tokens
are single-use** — persist the new one immediately on each successful
refresh, same gotcha we hit on the Vinted side.

---

## Photo upload — Tier 1

```http
POST https://api.kleinanzeigen.de/api/pictures.json
Authorization: Basic YW5kcm9pZDpUYVI2MHBFdHRZ
x-ecg-authorization-user: email=<email>,access=<JWT>
x-ebayk-userid-token: <opaque, from session boot>
x-ebayk-app: <UUID-ish + ts>
x-ebayk-groups: <experiment slugs>
User-Agent: Kleinanzeigen/2026.19.1 (Android 8.0.0; samsung SM-A320FL)
Content-Type: multipart/form-data; boundary=<custom>
```

Multipart body has a single part:

```
Content-Disposition: form-data; name="file"; filename="IMAGE_<uuid>.jpg"
Content-Type: image/jpeg
Content-Transfer-Encoding: binary

<jpeg bytes>
```

Response (201) is JAXB-JSON wrapping a `picture` with **multiple
size variants** in `link[].href` (rel=`thumbnail`, `teaser`, plus more):

```json
{"{http://www.ebayclassifiedsgroup.com/schema/picture/v1}picture": {
   "value": {
     "link": [
       {"href": "https://img.kleinanzeigen.de/api/v1/prod-ads/images/<…>?…", "rel": "thumbnail"},
       {"href": "https://…", "rel": "teaser"},
       …
     ]
   }
}}
```

For the listing submit we use the same picture's `<pic:link>` blocks.

---

## Listing submit — Tier 2

Two endpoint variants:

| Path | When |
|---|---|
| `POST /api/users/{user_id}/ads.json` | Direct submit (old flow, still works) |
| `POST /api/users/{user_id}/ads/articles` | **Upsell prompt** — returns paid-promo offers (Highlight/TopAd/Gallery), NOT a listing-create call |

The capture had **only `ads.json`** as the actual create. `/articles`
returned `{"articles":[…]}` upsell offers.

```http
POST https://api.kleinanzeigen.de/api/users/<user_id>/ads.json
Authorization: Basic YW5kcm9pZDpUYVI2MHBFdHRZ
x-ecg-authorization-user: email=<email>,access=<JWT>
x-ebayk-app: <UUID-ish + ts>
x-ebayk-userid-token: <opaque>
x-ebayk-wenkse-session-id: <session UUID, generated client-side>
x-ebayk-groups: <experiment slugs>
Content-Type: application/json; charset=utf-8     # ← but body is XML!
```

Body is **JAXB XML** (despite the JSON content-type — that's how the
server expects it):

```xml
<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
<ad:ad
    xmlns:types="http://www.ebayclassifiedsgroup.com/schema/types/v1"
    xmlns:cat="http://www.ebayclassifiedsgroup.com/schema/category/v1"
    xmlns:ad="http://www.ebayclassifiedsgroup.com/schema/ad/v1"
    xmlns:loc="http://www.ebayclassifiedsgroup.com/schema/location/v1"
    xmlns:attr="http://www.ebayclassifiedsgroup.com/schema/attribute/v1"
    xmlns:pic="http://www.ebayclassifiedsgroup.com/schema/picture/v1"
    xmlns:medias="http://www.ebayclassifiedsgroup.com/schema/media/v1"
    locale="en_US" id="0">
  <ad:title>T Shirt Olive grüb</ad:title>
  <ad:description>…multi-line, may include newlines, escape & as &amp;…</ad:description>
  <ad:contact-name>SneakerSupplierDE</ad:contact-name>
  <ad:imprint>…full Impressum block, only for COMMERCIAL accounts…</ad:imprint>
  <ad:email>sneakersupplierde@gmail.com</ad:email>
  <ad:poster-type><ad:value>COMMERCIAL</ad:value></ad:poster-type>     <!-- or PRIVATE -->
  <ad:ad-type><ad:value>OFFERED</ad:value></ad:ad-type>
  <cat:category id="160" />                                            <!-- e.g. 160 = Kleidung_Herren -->
  <loc:locations>
    <loc:location id="7615" />                                         <!-- numeric KA location id -->
  </loc:locations>
  <ad:ad-address />
  <ad:price>
    <types:price-type><types:value>SPECIFIED_AMOUNT</types:value></types:price-type>
    <types:amount>5</types:amount>
  </ad:price>
  <medias:medias />
  <pic:pictures>
    <pic:picture>
      <pic:link rel="thumbnail" href="<URL from /pictures.json response>" />
      <pic:link rel="teaser" href="…" />
      <!-- more variants if returned -->
    </pic:picture>
  </pic:pictures>
  <attr:attributes>
    <!-- per-category attributes; see /api/ads/metadata/{category_id}.json
         for the valid set + value enums for the chosen category -->
  </attr:attributes>
</ad:ad>
```

Response (201) — JAXB-JSON envelope echoing the created ad with
`ad-status: PENDING` (moderation queue) plus `category` block, `locations`
block, server-stamped `last-user-edit-date`, etc.

The new ad's listing ID isn't in the body; it's returned in the
`Location:` header (need to confirm in next capture, but standard JAXB
pattern).

---

## Per-category attributes — `metadata/{category_id}.json`

Before submitting, the app pre-fetches the valid attribute schema for
the chosen category:

```http
GET https://api.kleinanzeigen.de/api/ads/metadata/{category_id}.json
Authorization: Basic YW5kcm9pZDpUYVI2MHBFdHRZ
```

Returns the list of `<attr:attribute>` codes + value enums to embed in
the ad-submit XML. For our v1, we'll cache this per canonical category.

---

## Categories observed in capture

| KA category_id | Internal name | Localized label | Parent |
|---|---|---|---|
| 153 | (root for clothing) | Bekleidung | — |
| 160 | Kleidung_Herren | Herrenbekleidung | 153 |
| 22  | (clothing accessory) | — | — |
| 154 | Frauenbekleidung | Damenbekleidung | 153 |

For our 4 canon categories (jackets/jeans/tshirts/sneakers) we'll need to
either browse the full category tree (`gateway.kleinanzeigen.de/postad/api/v1/`)
or hand-pick from the public catalog page. Both Damen (154) and Herren (160)
have leaf clothing categories; the chosen one depends on user gender bias —
default to Damen since our training set skews that way.

---

## Optional — `gateway.kleinanzeigen.de/postad/api/v2/generate-ad`

Auto-generates title + description from a photo. Useful for the
"identification" loop but not strictly needed since our VLM already
emits these.

```http
POST https://gateway.kleinanzeigen.de/postad/api/v2/generate-ad
Authorization: Bearer <JWT>
```

Skip for v1 — we already have `to_kleinanzeigen` producing title +
description from the canonical English schema.

---

## Locations — `loc:location id="…"`

The `id` is a numeric KA location ID (7615 = "85051 Ingolstadt" per the
response echo). User's home location is set during onboarding. We can
either:
- Read it from `GET api.kleinanzeigen.de/api/users/{user_id}/profile.json`
  and cache per session
- Or hard-code based on whatever the maintainer's account profile says

For v1: cache from profile on first session; let the user edit on KA UI
if wrong.

---

## Akamai status

- **Login flow** (`login.kleinanzeigen.de`): Akamai BMP active
  (`/akam/13/...` + `_abck` cookie). Only relevant if we ever rebuild
  the login from scratch — for the demo, we don't (capture once, refresh forever).
- **Listing endpoints** (`api.kleinanzeigen.de`): no Akamai headers in
  the capture. Plain Tier-1 Basic + Tier-2 JWT, that's it. ✅
- **Akamai BMP appears in `api.kleinanzeigen.de/_bm/get_params`** at app
  cold-start. This is SDK init, not a guard on individual endpoints —
  publishing without those calls works (verified by the 201 above).

---

## Summary — what to build

For Phase 6c integration:

1. `KASession` dataclass: `access_token`, `refresh_token`, `expires_at`,
   `user_id`, `email`, `imprint` (for COMMERCIAL), `home_location_id`.
2. `refresh_access_token(session) -> KASession` — `POST /oauth/token` refresh grant.
3. `KAClient.upload_photo(image_path) -> picture_links: list[dict]`
   (multipart POST, parse JAXB-JSON response).
4. `KAClient.create_listing(ad_xml: str) -> listing_id`
   (build XML in JAXB shape, POST to `/api/users/{user_id}/ads.json`,
   parse Location header).
5. `to_kleinanzeigen(canon)` updates: emit JAXB-XML body with category_id,
   poster-type, picture links injected, attributes block from category metadata.
6. Onboarding: accept a session JSON from the user (refresh_token + initial
   access_token + user metadata, captured once via mitmproxy or pasted
   manually). **Don't try to programmatically log in** — Akamai BMP can't
   be defeated server-side without a real browser, and we'd need MFA SMS
   handling. If a real-browser login is wanted later, use Playwright like
   vinted-lister's web flow.
