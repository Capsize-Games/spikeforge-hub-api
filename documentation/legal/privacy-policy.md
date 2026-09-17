# Privacy Policy

**Effective date:** [fill in on publish]

SpikeForge Hub is operated by Capsize LLC, a Colorado limited liability
company ("Capsize", "we", "us"). This policy describes what personal
information the Hub collects, why, and what choices you have about it.

## What we collect

**Account information.** When you register with an email address and
password, we store that email address, an argon2id hash of your password
(never the password itself), the handle and display name you choose, and an
avatar URL if you set one.

**Linked sign-in providers.** If you sign in with a third-party provider
(for example GitHub or Google), we store that provider's name, the stable
account identifier it gives us, and the email address it reported at the
time you linked it. We do not store your password with that provider — we
never see it.

**Uploaded content.** If you publish a model to the Hub, we store the
artifact you upload, its checksum, the metadata you provide (name, version,
license, description), and any verification report our own tooling
generates about it. A published version is immutable and, once published,
is served publicly from our content delivery subdomain.

**Usage and security data.** We keep session and refresh tokens (as an
HTTP-only cookie and, for the desktop app, locally encrypted storage on
your own device) to keep you signed in, and ordinary web server access logs
(request time, path, and originating IP address) for operating and
securing the service.

**What we do not do.** We do not run third-party advertising trackers or
analytics scripts on the Hub, and we do not sell your personal information.

## Why we collect it

- To create and operate your account, including authenticating you and
  enforcing per-account storage limits.
- To let you publish, browse, and download models through the Hub.
- To verify your email address before allowing you to publish, and to
  contact you about your account, uploads, or a report against your
  content.
- To operate, secure, and troubleshoot the service.

## How long we keep it

An uploaded, published model version is immutable and is retained, and
served publicly, until it is removed under Content Removal below. Account
information is retained while your account is active. If you delete your
account (see below), we remove your email address, password hash, linked
provider identities, and display information; a tombstone record marking
that an account existed is kept so that your former handle is not silently
reassigned to someone else, and so that content you published before
deletion, if not separately removed, keeps a stable attribution.

## Content removal and account deletion

To request that your account be deleted, or that a specific model version
you no longer want hosted be removed, email **contact@capsize.online**.
This is currently a manual process: there is no self-serve "delete my
account" button in the product yet. We will confirm the request came from
the account holder before acting on it.

## Content posted by others

To report content that infringes your rights, violates the law, or
otherwise needs to come down, email **contact@capsize.online** with the
model's URL and the reason. Because published artifacts are served from a
public, cache-friendly address, removing a file stops it being served from
the Hub going forward but does not retroactively purge copies already
cached elsewhere.

## Your choices

You can review and update your account information by signing in. You can
unlink a connected sign-in provider if you have another way to sign in.
You can ask us to export or delete your account information at any time
by emailing **contact@capsize.online**.

## Governing law

This policy is governed by the laws of the State of Colorado, without
regard to its conflict-of-laws principles.

## Contact

Questions about this policy: **contact@capsize.online**.
