function parsearJSONRobusto(jsonString) {
    try {
        // Primeiro, limpa completamente a string
        let cleaned = jsonString
            .trim() // Remove espaços no início e fim
            .replace(/^[^{[]*/, '') // Remove qualquer coisa antes do primeiro { ou [
            .replace(/[^}\]]*$/, '') // Remove qualquer coisa depois do último } ou ]
            .trim();
    
        
        // Tenta parsear diretamente
        return JSON.parse(cleaned);
        
    } catch (error) {
        console.log('Primeira tentativa falhou, tentando abordagem alternativa...');
        
        try {
            // Abordagem mais agressiva para limpeza
            let cleaned = jsonString
                .trim()
                // Remove possíveis marcadores de código ou HTML
                .replace(/^```json\s*/i, '') // Remove ```json no início
                .replace(/```$/i, '') // Remove ``` no final
                .replace(/^[^{[]*/, '') // Remove qualquer coisa antes do primeiro { ou [
                .replace(/[^}\]]*$/, '') // Remove qualquer coisa depois do último } ou ]
                // Corrige problemas com aspas e escape
                .replace(/\\"/g, '"') // Remove escape desnecessário de aspas
                .replace(/\n/g, '\\n') // Escapa quebras de linha
                .replace(/\r/g, '\\r') // Escapa retornos de carro
                .replace(/\t/g, '\\t') // Escapa tabs
                .trim();
            
            console.log('String após limpeza agressiva:', cleaned.substring(0, 100) + '...'); // Debug
            
            return JSON.parse(cleaned);
            
        } catch (secondError) {
            console.error('Erro ao parsear mesmo após limpeza:', secondError);
            console.error('String que causou o erro:', jsonString.substring(0, 200));
            return null;
        }
    }
}

// Função para escapar tags HTML
function escaparTagsHTML(obj) {
    if (typeof obj === 'string') {
        return escapeHTMLRapido(obj);
    } else if (Array.isArray(obj)) {
        return obj.map(item => escapeHTMLRapido(item));
    } else if (typeof obj === 'object' && obj !== null) {
        const result = {};
        for (const key in obj) {
            if (obj.hasOwnProperty(key)) {
                result[key] = escapeHTMLRapido(obj[key]);
            }
        }
        return result;
    }
    return obj;
}


// Versão otimizada para performance
function escapeHTMLRapido(str) {
    return str.replace(/[&<>"']/g, function(m) {
        return {
            '&': '&amp;',
            '<': '&lt;',
            '>': '&gt;',
            '"': '&quot;',
            "'": '&#39;'
        }[m];
    });
}
