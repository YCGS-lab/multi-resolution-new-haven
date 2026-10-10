# Build, deploy, test

The site needs no build step to run: its JavaScript runs as written. Three
things around it do have tooling:

```mermaid
flowchart TB
  subgraph tooling["Tooling"]
    Vendor["scripts/website/vendor<br/>npm + esbuild"]
    Fixtures["benchmark/fixtures.py"]
    Bench["benchmark/bench.mjs<br/>Playwright"]
    TF["terraform/aws"]
  end
  Vendor -->|"just vendor"| Site[("website/<br/>vendor/ is committed")]
  Fixtures -->|"test COGs"| Site
  Site --> Serve["serve.py<br/>local, range requests"]
  Bench -->|"drives"| Serve
  Site -->|"just deploy: aws s3 sync"| S3[("S3 bucket")] --> CF["CloudFront<br/>HTTPS, HTTP/2 + 3"]
  TF -.->|"creates"| S3 & CF
```

| Piece | What | Page |
|---|---|---|
| Vendored bundle | deck.gl + deck.gl-raster as one committed ES module, rebuilt with `just vendor` | [Vendored bundle](./vendor) |
| Local server | `serve.py`: the repository root over HTTP, with range requests | [Local development](./local) |
| Hosting | Terraform: private S3 bucket behind CloudFront, plus a minimal deploy identity; `just deploy` | [Deployment](./deploy) |
| Tests | Credential-free fixture COGs and a before/after benchmark in headless Chromium | [Fixtures and benchmark](./benchmark) |

There are no unit tests. The renderer was checked by comparing screenshots
against the previous version product by product, and is measured by the
benchmark.
