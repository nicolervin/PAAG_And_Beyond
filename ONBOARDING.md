# Welcome to Process at a Glance

Welcome! This guide is the first thing every new collaborator should read, whether you are an Industrial Engineer, Advanced Quality Engineer, Ergonomist, Materials Planner, Advanced Manufacturing Engineer, or joining in another role. You do not need to be a programmer to get oriented or contribute thoughtfully.

## 1. What this project is

Process at a Glance is a local planning app for teams preparing a new assembly process. It keeps the product definition, parts, assembly order, work steps, timing, workstation balance, requirements, and open questions together instead of spreading them across separate spreadsheets. The app is still a prototype: it runs on one computer and stores its records and uploaded images locally. If no local data file exists, it starts with a small sample project so you can see how it works.

## 2. Setup — get the app running on your computer

### Clone the repository from GitHub

1. Make sure Git is installed and that you have access to the project repository. If you are unsure, ask the project owner for help before continuing.
2. Open PowerShell or another command window.
3. Move to the folder where you want to keep the project.
4. Run:

```powershell
git clone https://github.com/nicolervin/PAAG_And_Beyond.git
cd PAAG_And_Beyond
```

### Install the project dependencies

The repository lists its required software packages in `requirements.txt`, but the current setup instructions do not explain how a new collaborator should create the Python environment or install those packages. The existing instructions assume a shared environment named `.venv` already exists one folder above the repository.

This is an onboarding gap for the project owner to fill in. Until those installation steps are documented, ask the project owner or an established collaborator to provide or help create the shared environment. Do not guess at the setup if the documented run command below does not work.

### Run the app

Once the shared environment is available, open PowerShell in the repository folder and run the command already documented by the project:

```powershell
..\.venv\Scripts\streamlit.exe run streamlit_app.py
```

Then open [http://localhost:8501](http://localhost:8501) in your web browser.

You will know it is working when the terminal shows a local Streamlit address and the browser opens the Process at a Glance app without an error. The Overview screen should load, and a small sample project may appear if there was no existing local data file.

## 3. The three rulebooks you must read before doing anything else

Do not write or ask Codex to write any code until you have read all three of these files.

- `AGENTS.md` is the working agreement for people and AI assistants contributing to the project. It explains the app, team roles, safe working practices, and the gates that must be followed before changing existing behavior or proposing something new.
- `DATA_DICTIONARY.md` is the authoritative guide to the app's data. It explains what each table is for, how records connect, and whether information belongs to the whole project or only to one planning scenario.
- `DESIGN_SYSTEM.md` contains the locked user-interface and behavior standards. It keeps saving, deletion, history, audit records, terminology, units, and other shared interactions consistent across the app.

These files exist so several people can contribute without accidentally creating competing workflows, breaking important data links, or making each screen behave differently.

## 4. How this team works

- One person works on one screen or tab per week. Weekly assignments are tracked in Trello so everyone can see who owns the current work.
- Work happens in a personal Git branch. Name it with your initials and a short description of the screen or task, such as `jr/parts-catalog-image-fix`.
- Every Friday, the team reviews completed work together. Branches are merged into `main` only after the team approves them.
- Any change that touches the **critical thread** requires group discussion and final approval from the project owner. The critical thread is the core chain connecting Product Architecture, Parts, Fishbone, Yamazumi, and Process at a Glance.
- Adding your role to the Collaborator Roles list is easy and does not require a special approval process. Claiming ownership or exclusive control of a data type, table, or module is different: that always requires project-owner approval.

When you are unsure whether a change affects someone else's screen or the critical thread, pause and ask. Catching overlap early is normal teamwork, not a problem.

## 5. Before you build anything new

`AGENTS.md` contains a New Module Proposal Gate. If you ask Codex to build a page, module, table, or feature that does not already exist in `DATA_DICTIONARY.md`, implementation should pause before any code is written.

Codex will ask what the new idea connects to, how it links back to the existing data, whether it belongs to the whole project or only one scenario, whether it truly needs a new table, and which design standards apply. Answer those questions honestly and completely. Do not skip past them even if Codex lets you.

After the questions are answered, the proposal is recorded in `DATA_DICTIONARY.md` under **Proposed modules — pending owner review**, including who proposed it and the date. If you cannot explain what the idea connects to, how it links into the critical thread, or whether it is project-wide or scenario-specific, bring it to the project owner before continuing.

## 6. A quick check before you start real work

Before your first real task, open Codex and paste the following prompt to confirm you understand the ground rules:

---

```text
I just read AGENTS.md, DATA_DICTIONARY.md, and DESIGN_SYSTEM.md for this project. Without writing any code, please:
1. Summarize in plain language the difference between project-wide and scenario-specific data in this app, using one real example of each from the current schema.
2. Name one standard from DESIGN_SYSTEM.md and describe what it requires.
3. Tell me what you would do, per AGENTS.md, if I asked you to build a brand new "Packaging plan" page right now.
```

---

Show your Codex response to the project owner before starting your first assigned screen. This just confirms the ground rules landed correctly — it's not a test, just a quick sanity check.

