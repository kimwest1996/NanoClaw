import os
from typing import Any, Optional
from langchain_core.language_models.chat_models import BaseChatModel
from dotenv import load_dotenv
'''
多模型适配(Factory)
'''
load_dotenv()

# 各大厂商官方的 OpenAI 兼容接口地址 (当用户未配置 BASE_URL 时作为兜底)
COMPATIBLE_BASE_URLS = {
    "aliyun": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "dashscope": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "z.ai": "https://open.bigmodel.cn/api/paas/v4",
    "tencent": "https://api.hunyuan.cloud.tencent.com/v1",
    "deepseek": "https://api.deepseek.com",
    "xiaomi": "https://api.xiaomimimo.com/v1",
}


def _xiaomi_defaults(model_name: str) -> dict[str, float]:
    if model_name == "mimo-v2-flash":
        return {"temperature": 0.3, "top_p": 0.95}
    return {"temperature": 1.0, "top_p": 0.95}


def get_provider(
    provider_name: str = "openai", 
    model_name: str = "gpt-4o-mini", 
    temperature: float = 0.0,
    base_url: Optional[str] = None,  # 允许外部传入
    api_key: Optional[str] = None,   # 允许外部传入
    **kwargs: Any
) -> BaseChatModel:
    """
    模型适配器工厂
    """
    provider_name = provider_name.lower()
    
    if provider_name in ["openai", "aliyun", "dashscope", "z.ai", "tencent", "deepseek", "xiaomi", "other"]:
        from langchain_openai import ChatOpenAI

        extra_body = kwargs.pop("extra_body", None)
        if provider_name == "deepseek":
            current_api_key = api_key or os.environ.get("DEEPSEEK_API_KEY")
            api_key_name = "DEEPSEEK_API_KEY"
            final_base_url = base_url or os.environ.get("DEEPSEEK_API_BASE")
            if extra_body is None:
                thinking_mode = os.environ.get("DEEPSEEK_THINKING_MODE", "disabled").strip().lower()
                if thinking_mode in {"disabled", "enabled"}:
                    extra_body = {"thinking": {"type": thinking_mode}}
        elif provider_name == "xiaomi":
            current_api_key = api_key or os.environ.get("MIMO_API_KEY") or os.environ.get("XIAOMI_API_KEY")
            api_key_name = "MIMO_API_KEY"
            final_base_url = base_url or os.environ.get("MIMO_API_BASE") or os.environ.get("XIAOMI_API_BASE")
            defaults = _xiaomi_defaults(model_name)
            if temperature == 0.0:
                temperature = defaults["temperature"]
            kwargs.setdefault("top_p", defaults["top_p"])
        else:
            current_api_key = api_key or os.environ.get("OPENAI_API_KEY")
            api_key_name = "OPENAI_API_KEY"
            final_base_url = base_url or os.environ.get("OPENAI_API_BASE")

        if not current_api_key:
            raise ValueError(f"未找到 API Key！请确保 .env 中配置了 {api_key_name}")

        if not final_base_url:
            final_base_url = COMPATIBLE_BASE_URLS.get(provider_name) 

        return ChatOpenAI(
            model=model_name, 
            temperature=temperature,
            api_key=current_api_key,
            base_url=final_base_url,
            extra_body=extra_body,
            **kwargs
        )

    elif provider_name == "anthropic":
        from langchain_anthropic import ChatAnthropic
        
        current_api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not current_api_key:
            raise ValueError("未找到 ANTHROPIC_API_KEY 环境变量！")
            
        final_base_url = base_url or os.environ.get("ANTHROPIC_BASE_URL")

        return ChatAnthropic(
            model_name=model_name, 
            temperature=temperature, 
            api_key=current_api_key,
            base_url=final_base_url,
            **kwargs
        )
        
    elif provider_name == "ollama":
        from langchain_community.chat_models import ChatOllama
        
        final_base_url = base_url or os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
        
        return ChatOllama(
            model=model_name, 
            temperature=temperature, 
            base_url=final_base_url,
            **kwargs
        )
        
    else:
        raise ValueError(f"不支持的模型提供商: {provider_name}")

# 测试模型调用    
# LLM = get_provider(provider_name='aliyun', model_name='glm-5')
# res = LLM.invoke('你是谁')
# print(type(res))
# print(res)
