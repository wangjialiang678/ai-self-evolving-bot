## Task Complexity Classification

### Simple Interactions (Use Sonnet)
- User greetings and introductions
- Basic Q&A without code generation
- Clarification requests
- Acknowledgments and confirmations
- Expected token range: 1500-2500

### Complex Tasks (Use Opus)
- Multi-file code generation or refactoring
- Architecture design and system analysis
- Debugging with context gathering
- Tasks requiring deep reasoning or planning
- Expected token range: 4000-8000

### Model Selection Logic
1. Analyze user intent from first message
2. If task involves code/architecture/debugging → Opus
3. If task is conversational/informational → Sonnet
4. If uncertain → default to Opus for safety