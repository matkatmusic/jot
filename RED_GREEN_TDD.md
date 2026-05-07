## use STRICT RED-GREEN TEST-DRIVEN DEVELOPMENT strategies.

Do not write any code that is meant to express specific behavior without first confirming that there is a test function to prove that code correctly expresses that behavior.  
# IMPORTANT: 
If a test function does not exist for the behavior you are trying to achieve, **create one**, following the **How to write the tests** guidelines below.

---

### PREPARING YOURSELF BEFORE WRITING ANY CODE:

Before you write any tests or any code:

1. explain to yourself in PLAIN ENGLISH (without code) the BEHAVIOR you're trying to achieve, and write it down.

2. Identify every action, behavior, object or thing used in your PLAIN ENGLISH description of the behavior. 

3. use **Proper Naming Conventions** (see below) to create Identifiers for every action, behavior, object, and thing that is required to express the BEHAVIOR you're trying to achieve. 

Follow the above steps to create code (for tests or production) that is easy to read and understand. 

---
## Proper Naming Conventions:

### Name things (variables or classes/objects) based on what they are: 

Example: 
- Description: the conversation summary, as a string.
- code: `std::string conversationSummary;`

Example:
- Description: An object (data structure) that stores the `What/Why/How/Open Questions/Next Steps` trailers for each commit made by the `/plate` background agent
- code: 

    ```cpp
    struct CommitTrailers {
        std::string what;
        std::string why;
        std::string how;
        std::string openQuestions;
        std::string nextSteps;
    };
    ```

### Name functions based on what they do:  

Example:
- Behavior: Spawn a tmux session with a specific name
- code: 
    ```py
    def tmux_spawnNewSessionWithSpecificName(name: str)
    ```

Example: 
- Behavior: create a new pane in a specific tmux session and return the ID of the new pane for easy referencing later:
- Function Name:
    ```py
    def tmux_createNewPaneInSession(session_name: str) -> str:
    ```

Example:
- Behavior: Create a commit in the current repository and return the hash of that new commit or an empty string if there are no changes to commit.
- code: 
    ```py
    def git_createCommit(repo: Path, message: str) -> str:
    ```

---
### How to write the tests: 
- Write the tests so that they conform to the following guidlines: 
    - PLAIN ENGLISH Step-based BEHAVIORAL descriptions expressed as comments in the body of the test function
    - what each step of the test should be proving.
    - make each step as granular as possible, which may mean breaking the step down into sub steps, which would have their own functions with associated tests. 

- Name the test functions using the convention `test_<behavior_being_tested>`


Example: 
```py
def test_verify_commit_summary_is_updated_on_new_commit(tmp_path: Path):
    # Scenario: Verify that `<function_name>` correctly updates the latest commit's "convo-summary" message when a new commit is made.
    # Steps:
    # a branch has a commit from convo-id A. 
    # another commit is made after from convo-id B.
    # The test should detect that the convo-id A commit has a 'convo-summary' message. 
    # The test should then run the function to remove the convo-summary from that commit.  
    # the test should assert the convo-id A commit does not have a convo-summary message. 
    # The test should then run the function that feeds the previous convo-summary into the agent so the new convo-summary can be generated. 
    # The function should write that new convo-summary onto the convo-id B commit.  
    # The test should check that the convo-id B commit has this new convo-summary message.  
    assert False # fails by default initially
```
- Then write the **failing** version of that test (RED phase). 
- Then write the MINIMUM code possible in **SEPARATE functions** that you call from this test function to make the test pass (GREEN phase).  

Example: 
```py
def test_verify_commit_summary_is_updated_on_new_commit(tmp_path: Path):
    # Scenario: Verify that `<function>` correctly updates the latest commit's "convo-summary" message when a new commit is made.
    # Steps:
    # a branch has a commit from convo-id A. 
    convo_A_trailers = CommitTrailers(convo_id= "A", convo_summary="A summary")
    git_createCommit(repo, message="A", trailers= convo_A_trailers)
    # another commit is made after from convo-id B.
    convo_B_trailers = CommitTrailers(convo_id="B", convo_summary="B summary")
    git_createCommit(repo, message="B", trailers= convo_B_trailers)
    # The test should detect that the convo-id A commit has a 'convo-summary' message. 
    result = git_getGitCommitTrailers(repo)
    assert result == convo_A_trailers
    # The test should then run the function to remove the convo-summary from that commit.  
    result = git_removeConvoSummaryFromCommit(repo)
    # the test should assert the convo-id A commit does not have a convo-summary message. 
    assert result != convo_A_trailers
    assert convo_A_trailers.convo_summary not in result.convo_summary
    # The test should then run the function that feeds the previous convo-summary into the agent so the new convo-summary can be generated. 
    result = simulate_derived_agent(convo_A_trailers.convo_summary)
    # The function should write that new convo-summary onto the convo-id B commit.  
    result = git_updateConvoSummaryInCommit(convo_B_trailers)
    # The test should check that the convo-id B commit has this new convo-summary message.  
    assert result.convo_summary == convo_B_trailers.convo_summary
```

- Then Iterate over each separate function’s code block until the test passes.  

### Granularity of tests is a GOOD thing

It is better to have lots of tiny tests than one giant test that tries to do too many things at once.  

for example, consider the following two functions: 
```py
def setGitUserConfigValue(repo: Path, config_key: str, config_value: str) -> None:
    run(["git", "config", config_key, config_value], cwd=repo)

def getGitUserConfigValue(repo: Path, config_key: str) -> str:
    return run(["git", "config", config_key], cwd=repo)
```

The following example test is Bad because it tests two different behaviors at once: 

```py
def test_setAndgetGitUserConfigValues(repo: Path): 
    # Test: verify setting and getting User Config values in a repo works correctly. 
    # Setup: create an empty repo
    repo = makeEmptyRepo(path=tmp_path) 
    # set the default user email used for commits
    setGitUserConfigValue(repo, USER_EMAIL_KEY, USER_EMAIL_VALUE)
    # set the default user name used for commits
    setGitUserConfigValue(repo, USER_NAME_KEY, USER_NAME_VALUE)
    # make sure the default user email used for commits is correct
    assert getGitUserConfigValue(repo, USER_EMAIL_KEY) == USER_EMAIL_VALUE
    # make sure the default user name used for commits is correct
    assert getGitUserConfigValue(repo, USER_NAME_KEY) == USER_NAME_VALUE
```

The following example test is Good because it only tests a single behavior:
```py
def test_setGitUserConfigValue(tmp_path: Path):
    # Test: verify setting and getting User Config values in a repo works correctly.
    # setup: create an empty repo
    repo = makeEmptyRepo(path=tmp_path)
    # Test action: set the default user email used for commits
    setGitUserConfigValue(repo, USER_EMAIL_KEY, USER_EMAIL_VALUE)
    # Test verification: make sure the singular value we set was set correctly.
    assert getGitUserConfigValue(repo, USER_EMAIL_KEY) == USER_EMAIL_VALUE
```
