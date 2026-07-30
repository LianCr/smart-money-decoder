import { useState } from "react";

function avatarColor(addr) {
  let h = 0;
  for (let i = 2; i < (addr || "").length; i++) h = (h * 31 + addr.charCodeAt(i)) % 360;
  return `hsl(${h}, 42%, 42%)`;
}

function avatarInitials(addr) {
  return (addr || "0x").slice(2, 4).toUpperCase();
}

export function Avatar({ profile }) {
  const [err, setErr] = useState(false);
  const addr = profile.address || "";
  if (profile.profile_image && !err) {
    return <img className="avatar" src={profile.profile_image} onError={() => setErr(true)} alt="" />;
  }
  return <div className="avatar" style={{ background: avatarColor(addr) }}>{avatarInitials(addr)}</div>;
}
