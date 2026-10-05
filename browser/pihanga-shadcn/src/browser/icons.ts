/**
 * Icons available by name to declarations that come from outside JS
 * (e.g. a Python backend: Button(before_icon="plus")). A generic bundle cannot
 * know which icons an app needs; this is a curated set. The registry is the
 * global `window._PihangaIcons`, so further icon packs can be separate scripts.
 */
import { registerIcon } from "@/cards/icons";
import {
  Plus, Minus, X, Check, ChevronDown, ChevronUp, ChevronLeft, ChevronRight, User, Users, Save,
  FileUp, FileDown, Trash2, Pencil, Search, Settings, RefreshCw, Info, AlertTriangle, Home,
  Car, Truck, Star, Heart, Mail, Calendar, Clock, Download, Upload, ExternalLink, MountainSnow,
  Play, Pause, Square, Filter, Menu, Eye, EyeOff, Copy, LogIn, LogOut,
} from "lucide-react";

const ICONS = {
  plus: Plus, minus: Minus, x: X, check: Check, down: ChevronDown, "chevron-down": ChevronDown,
  "chevron-up": ChevronUp, "chevron-left": ChevronLeft, "chevron-right": ChevronRight, user: User,
  users: Users, save: Save, load: FileUp, "file-up": FileUp, "file-down": FileDown, trash: Trash2,
  pencil: Pencil, search: Search, settings: Settings, refresh: RefreshCw, info: Info,
  warning: AlertTriangle, home: Home, car: Car, truck: Truck, star: Star, heart: Heart, mail: Mail,
  calendar: Calendar, clock: Clock, download: Download, upload: Upload, "external-link": ExternalLink,
  "mountain-snow": MountainSnow, play: Play, pause: Pause, stop: Square, filter: Filter, menu: Menu,
  eye: Eye, "eye-off": EyeOff, copy: Copy, "log-in": LogIn, "log-out": LogOut,
} as const;

for (const [name, el] of Object.entries(ICONS)) {
  // Tolerate a page that loads two bundles registering the same icon name.
  try {
    registerIcon(name, el);
  } catch {
    /* already registered */
  }
}
