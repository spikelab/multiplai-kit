# Prompt Engineering Reference

A synthesis of Anthropic's official prompt engineering best practices, optimized for creating system prompts and instructions for Claude.

**Last Updated:** 2026-02-25

---

## Core Philosophy

**Claude responds best to explicit instructions.** Think of Claude as a skilled colleague who just joined—they have expertise but zero context about your specific needs. The clearer your explanation, the better the result.

**Golden Rule:** If a colleague couldn't follow your instructions to produce the result you want, Claude can't either.

---

## The 10-Element Framework

Not every prompt needs all elements. Start comprehensive, then remove what's unnecessary.

### 1. Task Context (Role)
Establish Claude's role early. Roles enhance performance across writing, coding, and analysis.

```
You are an experienced TypeScript developer who prioritizes readable, maintainable code over clever solutions.
```

**Best practices:**
- Be specific—"senior backend engineer" beats "developer"
- Include the audience: "explaining to junior developers" changes output dramatically
- Roles help with logic puzzles and complex reasoning

### 2. Tone Context
Specify communication style. Use a friendly, clear, and firm tone.

```
Be direct and concise. Avoid hedging language. If something is wrong, say so plainly.
```

### 3. Detailed Task Description
Expand on specific objectives, constraints, and boundaries. Use action verbs.

```
Review pull requests for:
- Security vulnerabilities
- Performance issues
- Code style violations

Do NOT:
- Suggest architectural changes unless asked
- Add comments to code that is self-explanatory
```

### 4. Examples (Most Effective Tool)
**Show, don't tell.** Examples are the single most effective technique for getting the output you want.

```xml
<example>
<input>Fix the login bug</input>
<output>The issue is in auth.ts:42. The session token comparison uses == instead of ===, causing type coercion failures. Fixed by changing to strict equality.</output>
</example>
```

**Best practices:**
- Provide 3-5 diverse examples for complex tasks (more = better performance)
- Use examples for tone/style rather than lengthy descriptions
- Format examples in XML tags for clarity
- Claude 4 pays close attention to examples—ensure they match desired behavior exactly

**Example quality criteria:**
- **Relevant**: Mirror your actual use case
- **Diverse**: Cover edge cases; vary enough to avoid unintended pattern-matching
- **Clear**: Wrap in `<example>` tags (multiple in `<examples>`)

**Pro tip:** Ask Claude to evaluate your examples for relevance and diversity, or generate more based on your initial set.

### 5. Input Data
Wrap variable content in XML tags to separate from instructions.

```xml
<user_code>
function add(a, b) { return a + b }
</user_code>

<error_message>
TypeError: Cannot read property 'map' of undefined
</error_message>
```

**Why XML tags:**
- Claude was trained to recognize them as organizational markers
- Prevents Claude from confusing data with instructions
- Enables clean extraction of outputs

**XML best practices:**
- Be consistent: Use the same tag names throughout and refer to them ("Using the contract in `<contract>` tags...")
- Nest tags for hierarchy: `<outer><inner></inner></outer>`
- Combine with other techniques: `<examples>`, `<thinking>`, `<answer>`

### 6. Immediate Task
Restate the specific action needed **near the end of the prompt**, not the beginning.

```
Given the code and error above, identify the root cause and provide a fix.
```

### 7. Precognition (Step-by-Step Reasoning)
For complex tasks, require visible reasoning before the final answer.

**Three levels of CoT (least to most powerful):**

1. **Basic** - Simple trigger phrase:
```
Think step-by-step before answering.
```

2. **Guided** - Specific steps to follow:
```
Before answering, first identify the relevant files, then list potential causes, then consider edge cases. Finally, provide your recommendation.
```

3. **Structured** - XML tags to separate reasoning from answer:
```
Think through this problem in <thinking> tags. First identify relevant files, then list potential causes, then consider edge cases. Finally, provide your recommendation in <answer> tags.
```

**Critical insight:** Reasoning only counts when it's explicit. Without outputting its thought process, no thinking occurs. Claude needs to write out the steps.

**When NOT to use CoT:** Not all tasks need deep thinking. Use judiciously—it increases output length and latency. Reserve for tasks a human would need to think through: complex math, multi-step analysis, decisions with many factors.

### 8. Output Formatting
Clarify expected response structure. Tell Claude what to do, not what to avoid:

```
# Less effective:
"Do not use markdown in your response"

# More effective:
"Your response should be composed of smoothly flowing prose paragraphs."
```

Or use XML format indicators:
```
Write the prose sections in <analysis> tags.
```

### 9. Constraints and Boundaries
Explicitly state what NOT to do. Define the box—constraints lead to creativity.

```
- Do not suggest using a different framework
- Do not refactor unrelated code
- Keep the response under 500 words
- Do not use the word "synergy"
- If you don't know, say "I don't know" rather than guessing
```

### 10. Explain the Why
Context behind instructions helps Claude generalize correctly.

```
# Less effective:
NEVER use ellipses

# More effective:
Your response will be read aloud by a text-to-speech engine, so never use ellipses since the TTS engine won't know how to pronounce them.
```

Claude is smart enough to generalize from explanations—it may also avoid other TTS-unfriendly patterns.

---

## Anti-Hallucination Techniques

### Give Claude an Out
```
Only answer if you're confident. If uncertain, say "I'm not sure about this."
```

### Require Evidence First
```
Before concluding, extract the relevant quotes from the documentation that support your answer.
```

### Investigate Before Answering
```
Never speculate about code you have not opened. If the user references a specific file, you MUST read the file before answering. Give grounded and hallucination-free answers.
```

### Use Scratchpad Reasoning
```
<scratchpad>
Work through your analysis here before giving the final answer.
</scratchpad>
```

---

## Verbosity Control

Explicitly command the level of detail:

```
# Expert level (verbose):
"Explain photosynthesis in detail for a college biology student. Work through your reasoning step by step."

# Brief:
"Explain photosynthesis. Be concise and use bullet points."

# Simple:
"Explain photosynthesis like I'm 5 years old."
```

---

## Power Phrases

These phrases trigger specific behaviors:

| Phrase | Effect |
|--------|--------|
| "Work through this step by step" | Forces visible reasoning, improves accuracy |
| "Critique your own response" | Self-correction and improvement |
| "Adopt the persona of an expert in [field]" | Domain-specific vocabulary and frameworks |
| "If the response is already correct, return it unchanged" | Prevents unnecessary changes during verification |
| "Go beyond the basics" | Encourages comprehensive output (Claude 4) |
| "Keep solutions simple and focused" | Prevents overengineering (Claude 4) |

---

## Draft-Plan-Act Workflow

Don't try to get perfect output in one prompt. Use iteration:

```
Step 1 (Plan):    "First propose an outline for this report"
Step 2 (Refine):  "In section two, add a subpoint about employee retention"
Step 3 (Execute): "Now write the full report based on this revised outline"
```

For complex tasks, break into subtasks:
```
Step 1: "Create a detailed table of contents for a business plan"
Step 2: "Write the executive summary based on our plan"
Step 3: "Now write the market analysis section"
Step 4: "Review the complete plan. Ensure consistent tone and check for contradictions"
```

### Self-Correction Chains
Have Claude review its own work for high-stakes tasks:

```
Prompt 1: "Summarize this research paper, focusing on methodology and findings."
Prompt 2: "Review this summary for accuracy and completeness. Grade A-F."
Prompt 3: "Update the summary based on the feedback."
```

**Parallel optimization:** For independent subtasks (analyzing multiple documents), run separate prompts in parallel for speed.

---

## Long-Running Agent Harnesses

For tasks spanning multiple context windows or sessions:

### Two-Phase Approach
Use different prompts for first session vs. subsequent sessions:

**First session (Initializer):** Set up foundational environment
- Create feature list, write init scripts, establish test framework

**Subsequent sessions (Worker):** Focus on incremental progress
- Read state files, pick one feature, implement, commit, update progress

### Feature List File (JSON, not Markdown)
Use JSON—it's less prone to inappropriate modifications than Markdown:

```json
// features.json
{
  "features": [
    {"id": 1, "name": "user_auth", "status": "passing", "tests": ["login", "logout", "session"]},
    {"id": 2, "name": "dashboard", "status": "failing", "tests": ["load", "filter", "export"]},
    {"id": 3, "name": "notifications", "status": "not_started", "tests": []}
  ]
}
```

**Critical:** Include in prompt: "It is unacceptable to remove or edit tests because this could lead to missing or buggy functionality."

### Progress Documentation
```
// progress.txt
Session 3:
- Fixed authentication token validation
- Updated user model for edge cases
- Next: investigate dashboard filter test failure
- Blocked: Need clarification on export format
```

### Init Script
Write an `init.sh` that starts servers and runs basic verification:
```bash
#!/bin/bash
# init.sh - run at start of each session
npm install
npm run dev &
sleep 3
curl -s http://localhost:3000/health | grep "ok"
```

Saves tokens by eliminating repetitive setup discovery.

### Session Startup Checklist
Prompt agents to begin each session by:
1. Confirm working directory (`pwd`)
2. Read progress files and git history
3. Run init script / basic verification
4. Select highest-priority incomplete feature
5. Work on ONE feature, commit, update progress

### Use Git for State
Git provides checkpoints and logs. Claude 4 models excel at using git to track state across sessions. Descriptive commits enable reverting failed changes.

### Key Failure Modes to Prevent

| Problem | Solution |
|---------|----------|
| Attempting entire app at once | Structured feature breakdown, one per session |
| Undocumented progress | Git commits + progress.txt |
| Premature completion claims | Explicit testing requirements, "passing": false default |
| Rediscovering how to run app | Pre-written init.sh script |
| Tests getting deleted/modified | JSON format + explicit prohibition in prompt |

---

## Long Context Tips

For prompts with large documents (20K+ tokens):

### Document Placement
**Put longform data at the TOP**, above your query, instructions, and examples. Query at the end can improve response quality by up to 30%.

```
<documents>
  <document index="1">
    <source>annual_report_2023.pdf</source>
    <document_content>
      {{ANNUAL_REPORT}}
    </document_content>
  </document>
  <document index="2">
    <source>competitor_analysis.xlsx</source>
    <document_content>
      {{COMPETITOR_ANALYSIS}}
    </document_content>
  </document>
</documents>

Analyze the annual report and competitor analysis. Identify strategic advantages.
```

### Ground Responses in Quotes
For long document tasks, ask Claude to quote relevant parts first. This cuts through noise:

```
Find quotes from the patient records relevant to diagnosing the symptoms. Place these in <quotes> tags. Then, based on these quotes, provide your diagnosis in <diagnosis> tags.
```

---

## Prompt Structure Template

```markdown
# Role
You are [specific role with relevant expertise].

# Context
[Background information Claude needs. Explain WHY this matters.]

# Task
[Clear, action-oriented description of what needs to be done]

# Constraints
- [What NOT to do]
- [Boundaries and limitations]
- [Keep solutions simple and focused]

# Format
[Expected output structure—show, don't describe]

# Examples
<example>
<input>[sample input]</input>
<output>[ideal output]</output>
</example>

# Input
<data>
[The actual content to process]
</data>

# Instruction
[Restate the immediate task at the end—use action verbs]
```

---

## Key Principles Checklist

### Clarity
- [ ] Would a colleague understand these instructions?
- [ ] Are format requirements explicit (not assumed)?
- [ ] Are constraints stated directly?
- [ ] Is the "why" explained for important rules?

### Structure
- [ ] Is data separated from instructions with XML tags?
- [ ] Is the main task restated near the end?
- [ ] Are examples provided for complex outputs?

### Accuracy
- [ ] Does Claude have permission to say "I don't know"?
- [ ] Is step-by-step reasoning requested for complex tasks?
- [ ] Is Claude required to investigate before answering?

### Enforcement
- [ ] Does every "don't do X" have a verification step? (Count, check, report — not just "avoid")
- [ ] Does every "limit to Y" have a hard cap with a cumulative counter?
- [ ] Does every "only if Z" have a checklist of conditions to verify before proceeding?
- [ ] Does every threshold require the model to report current value vs limit?

**Why this matters:** Instructions without verification mechanisms get ignored. "Limit m-dashes to 3" → 18 used. "Count m-dashes, report count, rewrite if >3" → works. This applies to ALL constraints, not just style rules.

### Quality
- [ ] Is the prompt free of typos? (Messy input → messy output)
- [ ] Are unnecessary elements removed?
- [ ] Is the role specific enough?
- [ ] Does it prevent overengineering?

---

## Common Mistakes

1. **Assuming Claude will infer intent** — Be explicit about everything
2. **Putting the task at the top** — Main instruction works better near the end
3. **Describing format instead of showing it** — Examples beat descriptions
4. **Not separating data from instructions** — Use XML tags
5. **Forgetting to give an "out"** — Let Claude admit uncertainty
6. **Vague roles** — "You are an expert" is useless; be specific
7. **Skipping examples for complex tasks** — Examples are the #1 tool
8. **Using "think" unnecessarily** — Triggers extended thinking in Claude 4
9. **Saying what NOT to do instead of what TO do** — Positive instructions work better for format
10. **Not explaining the why** — Context helps Claude generalize correctly
11. **Requesting suggestions when you want action** — Be explicit: "change" not "suggest"

---

## Quick Reference

| Technique | When to Use |
|-----------|-------------|
| Role prompting | Complex tasks, specific expertise needed |
| XML tags | Separating data from instructions |
| Examples (3-5) | Complex outputs, specific formats |
| Step-by-step (CoT) | Multi-step reasoning, math, logic |
| Give an out | Factual questions, uncertainty possible |
| Explain the why | Rules that need generalization |
| Prefilling* | Forcing specific output format (API only) |
| Task at end | Always—put main instruction last |
| Data at top | Long context (20K+ tokens) |
| Quote first | Long documents—ground in evidence |
| Draft-plan-act | Complex deliverables, reports |
| Self-correction | High-stakes tasks—review own work |
| Constraints | Creative tasks, specific requirements |
| Verbosity control | When default length is wrong |
| Anti-overengineering | Claude 4 coding tasks |
| Two-phase prompts | Long-running agents (init vs. worker) |
| Feature list (JSON) | Multi-session projects |
| Init script | Repeatable session startup |
| One feature per session | Prevent context exhaustion |

*Prefill caveats: Cannot end with trailing whitespace. Not supported with extended thinking.
