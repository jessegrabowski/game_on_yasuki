// WIP online-play lobby, served at the unlinked, password-gated /top-secret.html route until
// launch.

const lobbyStatus = document.getElementById("lobbyStatus");

if (lobbyStatus) {
  lobbyStatus.textContent = "Lobby loading…";
}
