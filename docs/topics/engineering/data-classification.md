# Data classification

Where a piece of information about this lab may be kept. This repository is public and its history is permanent, so the placement is decided before a fact is written, not after. The rule in [`docs/README.md#public-repo`](../../README.md#public-repo) is the short form; this page is the framework behind it: the classes, the questions that place a kind of information, and the rules that follow. How the framework is applied to the lab's own information, and what has been decided for each kind, is kept privately.

The stance is open: the practices, the designs and the governance are published, so anyone can read how the lab is run and reuse it. What is kept back is how those practices were exercised, what they found, and anything that would let a reader act as the maintainer.

## The classes

| Class | Where it lives | Holds |
| :--- | :--- | :--- |
| **Public** | This repository, its history, pull requests and Actions logs | Designs, behaviour on `main`, decisions and their reasons, practices and their cadence, what remains to be built and in what dependency order, and a record of finished work that shows no gap |
| **Private** | A private repository, and sessions the maintainer starts from it | Review findings, vulnerability assessment results, the results of exercises and drills, audit reports, and plans that carry dates of unavailability |
| **Local** | Outside every repository: the maintainer's machine, a chat, a scratch directory | Working records that name tests or sites no test guards, scratch inventories, session handovers |
| **Secret** | The secrets store, the maintainer's offline custody, a provider console | Credentials, keys, unseal material, and any value the public repository reads from the secrets store by key |

The classes are ordered by how few people may see them. A piece of information takes the most closed class that any part of it needs.

## Placing information

Ask in this order and stop at the first yes.

1. **Can a reader act as the maintainer, or as a system, with it?** A token, key, password, unseal share, recovery code or signed URL. It is Secret and is never written in a chat, a file or a commit message. One that was pasted anywhere is rotated.
2. **Is it an unpublished fact that something is wrong, weak or exposed?** A finding, a vulnerability and its fix state, an audit result, a gap an exercise found, an accepted risk with its reason. It is Private. A fix goes public as an ordinary change described by what it does.
3. **Does it say when something is or will be unavailable, unmonitored or unattended?** Dates of an absence, a shutdown, or a period in which a credential, certificate or lifecycle rule runs out. It is Private.
4. **Does combining it with public facts show a gap that neither shows alone?** A page that lines up what stops, what is unwatched and which clocks continue in a weakened state is classified by what it adds up to, not by its sentences. If the combination answers "what would be broken, and for how long", it is Private.
5. **Otherwise** it is Public.

A result, a date or a finding does not become Public by being reworded.

## Kinds of information

| Kind | Class |
| :--- | :--- |
| Decisions, topic docs, service records, and the dependency order of projects | Public |
| The exercise framework: its kinds, cadence, recovery tiers and how each exercise is run | Public |
| The results of exercises and drills, dated outcomes and what they found | Private |
| Code-review findings and the image vulnerability assessment | Private |
| Audit reports, result files and session handover notes | Private |
| Mutation-testing records | Local |
| Credentials, keys and values read from the secrets store | Secret |
| Tools that check or report on any of the above | Public; what they output follows the output's own kind |

## Rules

- **One-way references.** Public never cites private: no finding id, no assessment result, no tool name. Private may cite public by path or commit.
- **Time.** A completed, past action that shows no gap is public. A current or future state of weakness, and the dates that bound it, are private.
- **Reasons.** A reason that explains why something is urgent or unsafe is private, even when what is being done is public.
- **Open questions.** An unanswered question in a record, such as "Unknown: ... check ...", is public: it states no weakness. When it is checked, the answer is placed by the test, and a confirmed weakness is private until it is fixed.
- **Declassifying** is the maintainer's decision, made per kind and recorded privately. An agent never moves information to a more open class.
- **When unsure,** write the more closed class and say which question left it unclear. A private fact can be published later; a published one cannot be taken back.

## Checked and not checked

Gitleaks stops a credential in a commit, and the docs checks keep records and projects free of a security incident only by review. Nothing checks the rest mechanically: a placement is a decision made when the information is written.
