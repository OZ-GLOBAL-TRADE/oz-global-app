import importlib.util
from pathlib import Path

def load_active_plugins():
    """plugins klasöründeki Python eklentilerini tarar ve Gemini Tools yapısına çevirir."""
    plugin_dir = Path("plugins")
    plugin_dir.mkdir(exist_ok=True)
    
    tools = []
    for file in plugin_dir.glob("*.py"):
        if file.name.startswith("_"): continue
        
        try:
            spec = importlib.util.spec_from_file_location(file.stem, file)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            
            # Eklentinin içinde Gemini'nin çalıştıracağı (plugin_tool) fonksiyonu varsa al
            if hasattr(mod, "plugin_tool"):
                tools.append(mod.plugin_tool)
                print(f"[JARVIS] Eklenti Aktif: {file.name}")
        except Exception as e:
            print(f"[JARVIS] Eklenti yükleme hatası ({file.name}): {e}")
            
    return tools