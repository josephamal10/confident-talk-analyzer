// Signed-in user state and the login / sign-up view.
import { postJson, requestJson } from "./common.js";
import { navigate } from "./router.js";

const $ = (id) => document.getElementById(id);
let currentUser = null;
let nextPath = "/";
const listeners = [];

export function getUser() {
  return currentUser;
}

export function onAuthChange(listener) {
  listeners.push(listener);
}

function setUser(user) {
  currentUser = user;
  document.querySelectorAll(".auth-only").forEach((element) => element.classList.toggle("hidden", !user));
  document.querySelectorAll(".guest-only").forEach((element) => element.classList.toggle("hidden", Boolean(user)));
  $("userChip").textContent = user ? user.name : "";
  listeners.forEach((listener) => listener(user));
}

export async function loadUser() {
  try {
    setUser((await requestJson("/me")).user);
  } catch {
    setUser(null);
  }
  return currentUser;
}

// Sends guests to the login view and brings them back to `path` afterwards. Returns true if signed in.
export function requireLogin(path) {
  if (currentUser) return true;
  navigate(`/login?next=${encodeURIComponent(path)}`);
  return false;
}

export function sessionExpired(path) {
  setUser(null);
  requireLogin(path);
  setAuthStatus("Your session has expired. Please log in again.", "error");
}

export function showLogin(query) {
  nextPath = query.get("next") || "/";
  setAuthStatus(nextPath.startsWith("/practice") ? "Log in or create a free account to record and save your practice." : "");
}

function setAuthStatus(message, type = "") {
  const status = $("authStatus");
  status.className = "status-line";
  if (type === "error") status.classList.add("status-error");
  if (type === "ok") status.classList.add("status-ok");
  status.textContent = message;
}

function setActiveTab(tabName) {
  document.querySelectorAll(".tab-btn").forEach((button, index) => {
    const active = button.dataset.tab === tabName;
    button.classList.toggle("active", active);
    if (active) $("tabGlider").style.transform = `translateX(${index * 100}%)`;
  });
  $("loginForm").classList.toggle("active", tabName === "login");
  $("registerForm").classList.toggle("active", tabName === "register");
  setAuthStatus("");
}

function updatePasswordStrength() {
  const password = $("registerPassword").value;
  const score = [password.length >= 8, /[A-Z]/.test(password), /[0-9]/.test(password), /[^A-Za-z0-9]/.test(password)].filter(Boolean).length;
  const bar = $("strengthBar");
  bar.style.width = ["20%", "35%", "60%", "80%", "100%"][score];
  bar.style.backgroundColor = ["#ef4444", "#f97316", "#f59e0b", "#3b82f6", "#1d4ed8"][score];
  $("strengthLabel").textContent = `Password strength: ${["weak", "fair", "good", "strong", "excellent"][score]}`;
}

export function initAuth() {
  document.querySelectorAll(".tab-btn").forEach((button) => button.addEventListener("click", () => setActiveTab(button.dataset.tab)));
  document.querySelectorAll(".ghost-icon").forEach((button) => {
    button.addEventListener("click", () => {
      const input = $(button.dataset.toggle);
      const show = input.type === "password";
      input.type = show ? "text" : "password";
      button.textContent = show ? "Hide" : "Show";
    });
  });
  $("registerPassword").addEventListener("input", updatePasswordStrength);
  updatePasswordStrength();

  $("loginForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    const button = $("loginSubmit");
    button.disabled = true;
    button.textContent = "Signing In...";
    setAuthStatus("Authenticating...");
    try {
      const result = await postJson("/login", { email: $("loginEmail").value.trim(), password: $("loginPassword").value });
      $("loginForm").reset();
      setAuthStatus("");
      setUser(result.user);
      navigate(nextPath);
    } catch (error) {
      setAuthStatus(error.message, "error");
    } finally {
      button.disabled = false;
      button.textContent = "Sign In";
    }
  });

  $("registerForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    const button = $("registerSubmit");
    const email = $("registerEmail").value.trim();
    button.disabled = true;
    button.textContent = "Creating...";
    setAuthStatus("Creating your account...");
    try {
      const result = await postJson("/register", { name: $("registerName").value.trim(), email, password: $("registerPassword").value });
      $("registerForm").reset();
      updatePasswordStrength();
      setActiveTab("login");
      $("loginEmail").value = email;
      setAuthStatus(`${result.message} Please log in.`, "ok");
    } catch (error) {
      setAuthStatus(error.message, "error");
    } finally {
      button.disabled = false;
      button.textContent = "Create Account";
    }
  });

  $("logoutBtn").addEventListener("click", async () => {
    try {
      await postJson("/logout", {});
    } catch {
      // The server session is gone either way.
    }
    setUser(null);
    navigate("/");
  });
}
