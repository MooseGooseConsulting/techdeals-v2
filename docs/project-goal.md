# Project goal and design basis

My understanding is that **the goal is to make heterogeneous hardware information understandable, comparable, and useful for analysis—from the original source evidence through to the answer you get from a query.**

The difficult part is preserving what the information means. We need to distinguish:

- What an item is and which configuration it has.
- What is included, absent, optional, or separately purchasable.
- What the seller’s price actually covers.
- Which offers can reasonably be compared.
- What changed over time.
- What remains unknown or contradictory, with the evidence available to inspect.

An LLM producing valid JSON is one step in that process. Database rows, a confidence number, or a successful SQL query do not establish that the interpretation or answer is correct.

**We are not matching an existing schema because this experiment needs to establish the right representation before accepting the restrictions of an existing implementation.** The production schema is one implementation to evaluate. The current v2 schema is another. Neither earns correctness from already existing.

For example, if a schema requires a known product identity before it can retain a listing, it may lose useful unresolved information. If it represents a configured server as a single product without preserving its contents, it may erase the differences that determine price. If it treats every extracted component as independently purchasable, it can answer “cheapest DIMM” with a DIMM inside a server that must be bought whole.

Those are reasons to test and potentially replace a schema. They are not reasons to invent everything afresh. We should investigate existing approaches and reuse mechanisms that fit. **Greenfield gives us freedom to choose; it does not prove that our choices are better.**

I think our actual goal should be:

> **Demonstrate one coherent path that turns varied real hardware listings into correct, traceable buying and analysis answers, while retaining incomplete information and making uncertainty visible. Use that demonstration to decide which data model and implementation deserve to become part of the main project.**

That means proving a few demanding things together:

1. **Preserve the evidence.** Retain useful input even when identity, fetch time, or interpretation is incomplete. Missing information must stay missing; it must not become a fabricated fact.
2. **Represent the purchase correctly.** Six 600GB drives remain six drives of 600GB each. Two different NICs remain distinct. An optional upgrade does not become installed hardware. A server’s asking price remains attached to the purchase it covers.
3. **Support useful comparison and querying.** The system must return the right offers and exclude misleading matches. Two servers with the same chassis and CPU may still have materially different configurations.
4. **Preserve continuity.** Reprocessing a capture must not silently move prices to different items, duplicate offers, or erase history. A later capture must be distinguishable from a new interpretation of old evidence.
5. **Demonstrate the answer through the application.** We need to inspect what the consumer actually receives and trace its selected facts and prices back to evidence.

The schema, parser, identity rules, and queries should be chosen to satisfy those requirements together. That also gives us a basis for deciding which columns are needed: each needs a concrete meaning, a useful responsibility, and evidence that its producer and consumer preserve that meaning.

Eventually enhancing production is the intended use of the proven result. It does not require keeping production’s present design, importing all of v2, or repairing every existing module. We may retain some mechanisms, replace others, and change the main project where the evidence shows a better approach. **The experiment succeeds when it establishes a trustworthy way to organize and use the information—not when we finish polishing its current code.**
