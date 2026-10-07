import json
from django.shortcuts import render
from django.http import JsonResponse
from django.contrib.auth import authenticate, login, logout
from django.views.decorators.csrf import ensure_csrf_cookie

@ensure_csrf_cookie
def dashboard(request):
    """
    Vista principal que renderiza el panel de monitoreo Centinela.
    """
    return render(request, 'monitoreo/centinela.html')


def api_login(request):
    """
    Endpoint para autenticación de usuarios (Admin o Supervisor).
    """
    if request.method != 'POST':
        return JsonResponse({'ok': False, 'error': 'Método no permitido'}, status=405)

    try:
        # Permite recibir tanto JSON como form-data
        if request.content_type == 'application/json':
            data = json.loads(request.body)
            username = data.get('username', '').strip()
            password = data.get('password', '').strip()
        else:
            username = request.POST.get('username', '').strip()
            password = request.POST.get('password', '').strip()

        user = authenticate(request, username=username, password=password)

        if user is not None:
            if not user.is_active:
                return JsonResponse({'ok': False, 'error': 'El usuario está desactivado.'}, status=403)

            login(request, user)
            is_admin = bool(user.is_superuser or user.is_staff)

            return JsonResponse({
                'ok': True,
                'user': {
                    'username': user.username,
                    'name': user.first_name or user.username,
                    'role': 'Administrador' if is_admin else 'Supervisor',
                    'is_admin': is_admin,
                }
            })
        else:
            return JsonResponse({'ok': False, 'error': 'Usuario o contraseña incorrectos.'}, status=401)

    except Exception as e:
        return JsonResponse({'ok': False, 'error': f'Error en el servidor: {str(e)}'}, status=500)


def api_logout(request):
    """
    Cierra la sesión del usuario actual.
    """
    logout(request)
    return JsonResponse({'ok': True})


def api_me(request):
    """
    Retorna la información del usuario autenticado actualmente.
    """
    if request.user.is_authenticated:
        is_admin = bool(request.user.is_superuser or request.user.is_staff)
        return JsonResponse({
            'authenticated': True,
            'user': {
                'username': request.user.username,
                'name': request.user.first_name or request.user.username,
                'role': 'Administrador' if is_admin else 'Supervisor',
                'is_admin': is_admin,
            }
        })
    return JsonResponse({'authenticated': False})
