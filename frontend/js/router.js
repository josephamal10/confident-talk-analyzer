// Tiny hash router: "#/practice/jam?x=1" -> handler({ mode: "jam" }, URLSearchParams("x=1")).
const routes = [];
let notFound = () => {};

export function route(pattern, handler) {
  const names = [];
  const regex = new RegExp(
    `^${pattern.replace(/:[a-zA-Z]+/g, (match) => {
      names.push(match.slice(1));
      return "([^/]+)";
    })}$`
  );
  routes.push({ regex, names, handler });
}

export function fallback(handler) {
  notFound = handler;
}

export function currentPath() {
  return window.location.hash.slice(1) || "/";
}

export function navigate(path) {
  if (currentPath() === path) resolve();
  else window.location.hash = path;
}

function resolve() {
  const [path, query = ""] = currentPath().split("?");
  for (const { regex, names, handler } of routes) {
    const match = path.match(regex);
    if (match) {
      const params = Object.fromEntries(names.map((name, index) => [name, decodeURIComponent(match[index + 1])]));
      handler(params, new URLSearchParams(query));
      return;
    }
  }
  notFound();
}

export function startRouter() {
  window.addEventListener("hashchange", resolve);
  resolve();
}
