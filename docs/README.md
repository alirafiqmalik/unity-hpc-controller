# Documentation

Start with the [project README](../README.md), then follow the guide for your role.

| Goal | Read |
|---|---|
| Configure the controller, submit tasks, retrieve files | [Backend operations and HTTP contract](backend-campaigns.md) |
| Establish noninteractive cluster access | [SSH access](guides/ssh-access.md) |
| Understand project, runner, plugin, and controller ownership | [Component ownership](guides/component-ownership.md) |
| Follow the execution flow and durable stores | [Architecture](../ARCHITECTURE.md) |
| Find the module that implements a behavior | [Controller source map](../controller/README.md) |
| Try a small portable task | [CPU result example](../examples/cpu-result/README.md) |
| Check what cluster measurements actually establish | [Capability assessment](research/unity-backend-capabilities.md) |
| Use the project's domain language | [Glossary](../CONTEXT.md) |
| Contribute and verify a change | [Contributing](../CONTRIBUTING.md) |

## Organization

- `guides/`: practical setup and responsibility boundaries.
- `research/`: dated evidence, upstream comparisons, and measurement limits.
- `adr/`: architecture decisions and their supersession history.
- `agents/`: issue tracking, triage labels, and domain conventions.
- `assets/`: source diagrams used by the README.
- `backend-campaigns.md`: the canonical combined operator and API reference.

[ADR 0009](adr/0009-headless-campaign-controller.md) defines the current campaign
contract. ADRs 0001, 0002, 0006, and 0008 are historical. Older research may
mention removed interfaces; use the current guides for operating instructions.

The runtime directories and command paths remain stable because installed
plugins, deployed services, and remote collection scripts depend on them.
Examples and documentation are separate from the controller's implementation.
