/** Entry point of the generic bundle: runtime + all shadcn cards + icons. */
import "./index.css";
import "./cards";
import "./icons";
import { Toaster } from "sonner";
import { startRemote } from "./start";

startRemote({ extras: <Toaster />, log: new URLSearchParams(location.search).has("pilog") });
