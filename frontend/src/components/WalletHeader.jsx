import { abbrev } from "../utils/format.jsx";
import { Avatar } from "./Avatar.jsx";

export function WalletHeader({ profile }) {
  const addr = profile.address || "";
  const nick = profile.name || profile.pseudonym || abbrev(addr);
  return (
    <div className="wallet-head">
      <Avatar profile={profile} />
      <div className="wmeta">
        <div className="wnick">{nick}</div>
        <div className="waddr num">{addr}</div>
      </div>
    </div>
  );
}
