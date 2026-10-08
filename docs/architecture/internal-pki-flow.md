# Internal PKI: Issuance and Renewal

How an app's TLS certificate gets issued by step-ca once and renewed on a timer afterwards — spans
[`step-ca.md`](../topics/services/step-ca.md), [`lldap.md`](../topics/services/lldap.md) and
[`openbao.md`](../topics/secrets/openbao.md), which each use the same `step_ca_cert` role and differ only
in how the app picks up a renewed certificate.

## Issuance (once, in `deploy.yaml` Play 6)

Issuance needs the provisioner password, because there is no certificate yet to authenticate with.

```mermaid
sequenceDiagram
    participant Role as step_ca_cert role
    participant Step as step-cli container
    participant CA as step-ca
    participant Vol as app_certs volume
    participant App as app container

    Role->>Vol: certificate already there?
    Note over Role,Vol: if yes, compare its names to the requested ones and stop
    Role->>Role: write provisioner password to a 0600 scratch file
    Role->>Step: run step ca certificate (JWK provisioner)
    Step->>CA: request, authenticated by the password
    CA-->>Step: signed certificate
    Step->>Vol: fullchain.pem, privkey.pem
    Role->>Vol: chown to the app's user, if the image needs it
    Role->>App: restart so it loads the certificate
    Role->>Role: delete the scratch password file
    Role->>Role: install cert-renewer units and enable the timer
```

## Renewal (every timer firing, on the host)

Renewal authenticates with the existing certificate over mTLS, so it never touches the provisioner password.

```mermaid
sequenceDiagram
    participant Timer as cert-renewer@app.timer
    participant Svc as cert-renewer@app.service
    participant Step as step-cli container
    participant CA as step-ca
    participant Vol as app_certs volume
    participant App as app container
    participant Out as Telegram / Uptime Kuma

    Timer->>Svc: start
    Svc->>Step: ExecCondition: step certificate needs-renewal
    Step->>Vol: read fullchain.pem
    alt not due
        Step-->>Svc: exit 1, unit skipped
    else due
        Svc->>Step: ExecStart: step ca renew (mTLS)
        Step->>CA: renew with the current certificate
        CA-->>Step: renewed certificate
        Step->>Vol: overwrite fullchain.pem, privkey.pem
        Svc->>Vol: ExecStartPost: chown, if CHOWN_IMAGE is set
        alt RENEW_ACTION=signal
            Svc->>App: docker kill --signal=HUP
        else restart
            Svc->>App: docker compose restart
        end
        Svc->>Out: OnSuccess: Uptime Kuma push
    end
    Note over Svc,Out: any failure runs OnFailure: telegram-notify@app
```

Which action an app uses is in its own `/etc/cert-renewer/<app>.env`: OpenBao sends `SIGHUP` so a renewal doesn't
reseal it ([`openbao.md`](../topics/secrets/openbao.md#cert-renewal-uses-sighup-not-a-restart)), and lldap restarts.
