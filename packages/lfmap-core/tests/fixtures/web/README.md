# Web fetcher test fixtures

Offline harness for the `web.fetch` core tests (`docs/specs/web-plugin.md` section 11). Nothing here is a secret:
the key exists only so the fake HTTPS server on `127.0.0.1` can present `cert.pem`.

- `cert.pem`, `key.pem`: self-signed EC P-256 certificate for `fake.test`, `other.test` and `blocked.test`
  (subjectAltName), valid for 100 years. Made once with OpenSSL 3.0:

  ```
  openssl req -x509 -newkey ec -pkeyopt ec_paramgen_curve:prime256v1 -nodes -keyout key.pem -out cert.pem \
    -days 36500 -subj "/CN=fake.test" \
    -addext "subjectAltName=DNS:fake.test,DNS:other.test,DNS:blocked.test" \
    -addext "keyUsage=critical,digitalSignature,keyCertSign" -addext "extendedKeyUsage=serverAuth"
  ```

- `harness.py`: the fake server (`FakeServer`, routes with status, headers, body and pacing; counts requests and
  body bytes sent), the resolver stub (`StubResolver`) and the socket guard (`SocketGuard`). The `test_web_*.py`
  files load it by path because pytest runs with `--import-mode=importlib`.
