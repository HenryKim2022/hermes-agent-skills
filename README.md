# 🛠️ Hermes Agent - Custom Backend & Skills Guide

This guide explains how to install custom skills (like `godmode`) and connect your Hermes Agent to a custom **9router** backend on Windows.

---

## 💾 Installation & Setup Steps

Follow these steps in order to configure your device.

### Step 1: Open the Config Directory
1. Open your Windows File Explorer.
2. Go to your user directory folder:
   ```text
   C:\Users\Administrator\.hermes\
   ```

### Step 2: Set Up Your API Keys
1. Look for a file named `.env` inside that folder. 
2. If it does not exist, create a new text file and name it exactly `.env`.
3. Open it with Notepad and paste your **9router** key:
   ```env
   OPENROUTER_API_KEY=your-9router-api-key-here
   ```
4. Save and close the file.

### Step 3: Configure the 9router Custom Backend
You need to tell Hermes to route all traffic to the 9router servers.

1. Open your Terminal/Command Prompt.
2. Run these two commands to automatically update your `config.yaml` file:
   ```bash
   hermes config set model.provider custom
   hermes config set model.base_url https://9router.com
   ```
3. Set your preferred AI model name by running:
   ```bash
   hermes config set model.model nousresearch/hermes-3-llama-3.1-405b
   ```
   *(Note: Replace `nousresearch/hermes-3-llama-3.1-405b` with the exact model you want to use from 9router).*

### Step 4: Install the Skill
If you have not done so already, run the installation command:
```bash
hermes skills install "https://github.com/HenryKim2022/hermes-agent-skills"
```
Press `y` and hit Enter when asked to confirm the dangerous verdict message.

### Step 5: Reload the Agent
Apply all settings by restarting the system configuration:
```bash
hermes reload
```

---

## 🚀 How to Use the Installed Skills

Once the installation is complete, use these commands to operate your skills.

### 1. Check Active Skills
Verify that your newly added skill is recognized by the system:
```bash
hermes skills list
```
You should see `godmode` listed under your active directory.

### 2. Launch the Chat Interface
Start talking to your agent powered by the new 9router backend:
```bash
hermes chat
```

### 3. Trigger the Skill Inside the Chat
While inside the active chat session, you can invoke the custom automated skill behaviors. 

* Use the dedicated slash command to start the red-teaming/godmode utility environment:
  ```text
  /godmode
  ```
* To view direct instructions and context rules inside the skill file itself, you can ask the agent:
  ```text
  "Read the SKILL.md file for godmode and summarize the main testing strategies."
  ```

---

## 🗑️ How to Uninstall
If you want to remove the skill and delete its script files from your computer later, run:
```bash
hermes skills uninstall godmode
hermes reload
```
