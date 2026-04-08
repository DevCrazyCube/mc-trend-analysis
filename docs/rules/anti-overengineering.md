# Anti-Overengineering Rules

These rules exist to prevent the system from becoming unnecessarily complex. Complexity has a real cost: it slows development, hides bugs, makes debugging harder, and makes onboarding new contributors nearly impossible.

The target is the minimum complexity that achieves the system's actual goals.

---

## Rule 1: No Abstractions for Single Use Cases

If a pattern appears exactly once, do not abstract it. Abstractions earn their cost only when they are used in three or more genuinely similar places.

Example of premature abstraction:
```python
class BaseScorer(ABC):
    @abstractmethod
    def compute_score(self, inputs: ScorerInputs) -> float:
        pass
```
...if there's only one scorer at the time of writing.

Write the function directly. Extract the abstraction only when you have concrete duplication to eliminate.

---

## Rule 2: No Configuration for Things That Don't Need to Change

Not everything needs to be configurable. Configurable parameters add cognitive load: someone has to understand what each configuration option does, what the valid ranges are, and what happens at extreme values.

Only make something configurable if:
- It will realistically change between environments (e.g., API keys, rate limits)
- It is a tunable parameter that will be adjusted as the system is calibrated (e.g., dimension weights)
- It is an operational setting that changes without code deployment (e.g., polling intervals)

Do not make something configurable "just in case" or "for flexibility."

---

## Rule 3: No Premature Performance Optimization

Do not optimize until you have measured a real performance problem.

This system processes thousands of tokens per day. Modern hardware can do this easily. Write clear, correct code first. Optimize specific hot paths after profiling confirms they are actually hot.

Prohibited pre-optimizations:
- Caching of values that haven't been measured as slow to compute
- Batch database operations for logic that is not confirmed to be a bottleneck
- Async everything before confirming that I/O is the bottleneck
- Custom data structures when standard library structures work fine

---

## Rule 4: No Agent for What a Function Can Do

If a task can be expressed as a function with deterministic logic, write the function. Do not introduce an LLM or agent because it "seems easier" to write a prompt than to write the logic.

Tests: Can the behavior be specified with examples? Can it be verified deterministically? Does it depend on real-world knowledge that changes? If the answer is "deterministic + no changing real-world knowledge," write a function.

See `docs/implementation/agent-strategy.md` for the full policy on when agents are acceptable.

---

## Rule 5: No Microservices Until Necessary

The system starts as a monolith (single deployable process). Do not split into microservices until:
- A specific component is scaling beyond the others and needs independent scaling
- A component needs a different deployment cadence
- Team size requires independent deployability

A premature microservices split adds: service discovery, network calls between services, distributed tracing, independent deployment pipelines, and inter-service authentication. These are real costs with no benefit at early stage.

---

## Rule 6: No Framework Until the Problem Is Clear

Do not introduce a new framework, library, or tool until you have confirmed it solves a real problem better than the current approach.

Pattern to avoid: "We should use X framework for the ingestion pipeline." This is often a solution looking for a problem.

Pattern to prefer: "The ingestion pipeline has this specific problem [describe it concretely]. X framework solves it by [describe the mechanism]. The tradeoff is [describe what we give up]."

Every new dependency has a cost in maintenance burden, upgrade risk, and cognitive load.

---

## Rule 7: No Generics for Specific Types

Don't write generic processing code when you have specific, known types.

Example:
```python
def process_record(record: Any) -> Any:
    if isinstance(record, TokenRecord):
        ...
    elif isinstance(record, EventRecord):
        ...
```

Write:
```python
def process_token_record(record: TokenRecord) -> ProcessedToken:
    ...

def process_event_record(record: EventRecord) -> ProcessedEvent:
    ...
```

Specific types are more readable, more debuggable, and better for type checking.

---

## Rule 8: No Nested Callbacks or Deep Async Chains

Async is useful. Async pyramids of doom are not. If you have more than two levels of callback nesting or async chains that are hard to trace, restructure the code.

If you cannot explain the execution order of a piece of async code to another developer in 30 seconds, it is too complex.

---

## Rule 9: No Wrapper Classes Around Simple Data

Do not wrap dictionaries or standard types in classes "for encapsulation" when a dataclass or simple typed dict would work fine.

If a data container:
- Has no methods (or only trivial accessors)
- Doesn't enforce invariants
- Doesn't extend behavior

...it does not need to be a class.

---

## Rule 10: Keep the Scoring Formula Simple

The probability framework defines a weighted linear combination. This is simple and auditable. Do not replace it with:
- Neural networks or ML models
- Multiplicative formulas with complex interactions
- Lookup tables with hundreds of entries
- Scoring trees with many conditional branches

If the simple formula doesn't calibrate well, understand why before adding complexity. Usually the issue is with input data quality or weight values, not the formula structure.

---

## The Test for Complexity

Before adding any significant complexity (new abstraction, new dependency, new pattern, new agent), ask:

1. **What specific problem does this solve?** (if you can't name it concretely, don't add it)
2. **Is this problem actually happening, or might it happen?** (solve real problems, not hypothetical ones)
3. **What is the simplest solution to this specific problem?** (start there, not at the complex solution)
4. **What does this cost?** (maintenance, cognitive load, onboarding, test coverage)
5. **Would removing this later be easy?** (if not, be extra careful adding it)

If the answers don't justify the complexity, don't add it.
